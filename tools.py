"""Herramientas que los agentes pueden usar. Para agregar una nueva:
1. Escribe la función (recibe argumentos simples y devuelve texto).
2. Regístrala en HERRAMIENTAS con su descripción y esquema.
3. Agrega su nombre a la lista de herramientas del agente en agents.py.
"""
import asyncio
import json
import re
import subprocess
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from config import CONFIRMAR_COMANDOS, MEMORIA_DIR, WORKSPACE

_lock_consola = threading.Lock()  # para que dos agentes no pregunten a la vez
_lock_memoria = threading.Lock()

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GranjaAgentes/1.0"

COMANDOS_BLOQUEADOS = [
    "rm -rf", "rm -r /", "rmdir /s", "rd /s", "del /s", "del /f", "del /q", "format ",
    "shutdown", "mkfs", "diskpart", "reg delete", ":(){", "remove-item -recurse",
    "remove-item -r", "stop-computer", "restart-computer", "cipher /w",
]


# =====================================================================
# Utilidades
# =====================================================================

def _ruta_segura(ruta: str) -> Path:
    p = (WORKSPACE / (ruta or ".")).resolve()
    if p != WORKSPACE and WORKSPACE not in p.parents:
        raise ValueError(f"Ruta fuera del workspace: {ruta}")
    return p


def _recortar(texto: str, limite: int = 8000) -> str:
    return texto if len(texto) <= limite else texto[:limite] + "\n...[recortado]"


def _normalizar_url(url: str) -> str:
    """Convierte tildes, ñ y espacios de la URL a su forma segura (Ocaña → Oca%C3%B1a)."""
    p = urllib.parse.urlsplit(url.strip())
    host = p.hostname.encode("idna").decode() if p.hostname else ""
    netloc = host + (f":{p.port}" if p.port else "")
    seguro = "/%:=&?~#+!$,;'@()*[]-._"
    return urllib.parse.urlunsplit((p.scheme, netloc, urllib.parse.quote(p.path, safe=seguro),
                                    urllib.parse.quote(p.query, safe=seguro), p.fragment))


def _http_get(url: str, timeout: int = 20, datos: dict | None = None) -> tuple[str, str]:
    """Devuelve (texto, content_type). Si `datos`, hace POST de formulario."""
    url = _normalizar_url(url)
    cuerpo = urllib.parse.urlencode(datos).encode() if datos else None
    req = urllib.request.Request(url, data=cuerpo, headers={
        "User-Agent": USER_AGENT, "Accept-Language": "es,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        tipo = r.headers.get("Content-Type", "")
        charset = r.headers.get_content_charset() or "utf-8"
        crudo = r.read(3_000_000)  # máx. 3 MB
    return crudo.decode(charset, errors="replace"), tipo


class _HtmlATexto(HTMLParser):
    IGNORAR = {"script", "style", "noscript", "nav", "footer", "header", "svg", "form", "aside"}
    BLOQUES = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"}

    def __init__(self):
        super().__init__()
        self.partes, self.titulo = [], ""
        self._ignorando, self._en_titulo = 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORAR:
            self._ignorando += 1
        elif tag == "title":
            self._en_titulo = True
        elif tag in self.BLOQUES:
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in self.IGNORAR and self._ignorando:
            self._ignorando -= 1
        elif tag == "title":
            self._en_titulo = False

    def handle_data(self, data):
        if self._en_titulo:
            self.titulo += data
        elif not self._ignorando:
            self.partes.append(data)


def html_a_texto(html: str) -> tuple[str, str]:
    """Convierte HTML en (titulo, texto limpio)."""
    p = _HtmlATexto()
    p.feed(html)
    texto = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.partes))
    texto = re.sub(r"\n\s*\n+", "\n\n", texto).strip()
    return p.titulo.strip(), texto


# =====================================================================
# Archivos y terminal
# =====================================================================

def leer_archivo(ruta: str) -> str:
    return _recortar(_ruta_segura(ruta).read_text(encoding="utf-8", errors="replace"))


def escribir_archivo(ruta: str, contenido: str) -> str:
    p = _ruta_segura(ruta)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenido, encoding="utf-8")
    return f"Guardado {ruta} ({len(contenido)} caracteres)"


def listar_archivos(ruta: str = ".") -> str:
    base = _ruta_segura(ruta)
    if not base.exists():
        return f"No existe: {ruta}"
    ignorar = {".git", "node_modules", "__pycache__", ".venv", "vendor", ".pytest_cache"}
    salida = []
    for p in sorted(base.rglob("*")):
        if any(parte in ignorar for parte in p.parts):
            continue
        salida.append(str(p.relative_to(WORKSPACE)).replace("\\", "/") + ("/" if p.is_dir() else ""))
        if len(salida) >= 300:
            salida.append("...[más archivos]")
            break
    return "\n".join(salida) or "(vacío)"


def ejecutar_comando(comando: str, timeout: int = 120) -> str:
    if any(b in comando.lower() for b in COMANDOS_BLOQUEADOS):
        return "Comando bloqueado por seguridad."
    if CONFIRMAR_COMANDOS:
        with _lock_consola:
            ok = input(f"\n⚠️  Un agente quiere ejecutar:\n   {comando}\n¿Permitir? (s/n): ")
        if ok.strip().lower() != "s":
            return "El usuario rechazó el comando. Busca otra forma o explica por qué lo necesitas."
    try:
        r = subprocess.run(
            comando, shell=True, cwd=WORKSPACE,
            capture_output=True, text=True, timeout=min(int(timeout), 600),
            encoding="utf-8", errors="replace",
        )
        return _recortar(f"código de salida: {r.returncode}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}")
    except subprocess.TimeoutExpired:
        return f"El comando superó {timeout}s y se detuvo."


# =====================================================================
# Web
# =====================================================================

def _parsear_ddg_html(html: str, maximo: int) -> list[dict]:
    resultados = []
    bloques = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]*class="result__a"|$)',
        html, flags=re.S)
    for href, titulo, resto in bloques:
        m = re.search(r"uddg=([^&]+)", href)
        url = urllib.parse.unquote(m.group(1)) if m else href
        if url.startswith("//"):
            url = "https:" + url
        if "duckduckgo.com/y.js" in url:  # anuncios
            continue
        snip = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', resto, flags=re.S)
        limpiar = lambda s: unescape(re.sub(r"<[^>]+>", "", s)).strip()
        resultados.append({"titulo": limpiar(titulo), "url": url,
                           "resumen": limpiar(snip.group(1)) if snip else ""})
        if len(resultados) >= maximo:
            break
    return resultados


def _buscar_ddgs(consulta, maximo, noticias):
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS  # nombre antiguo de la librería
    d = DDGS()
    crudos = d.news(consulta, max_results=maximo) if noticias else d.text(consulta, max_results=maximo)
    return [{"titulo": r.get("title", ""), "url": r.get("href") or r.get("url", ""),
             "resumen": r.get("body", ""), "fecha": r.get("date", "")} for r in crudos]


def _buscar_ddg_html(consulta, maximo):
    html, _ = _http_get("https://html.duckduckgo.com/html/", datos={"q": consulta, "kl": "wt-wt"})
    return _parsear_ddg_html(html, maximo)


def _buscar_wikipedia(consulta, maximo, idioma="es"):
    url = (f"https://{idioma}.wikipedia.org/w/api.php?action=query&list=search&format=json"
           f"&srlimit={maximo}&srsearch={urllib.parse.quote(consulta)}")
    datos = json.loads(_http_get(url)[0])
    return [{"titulo": r["title"],
             "url": f"https://{idioma}.wikipedia.org/wiki/{urllib.parse.quote(r['title'].replace(' ', '_'))}",
             "resumen": unescape(re.sub(r"<[^>]+>", "", r.get("snippet", "")))}
            for r in datos.get("query", {}).get("search", [])]


def buscar_web(consulta: str, max_resultados: int = 6, noticias: bool = False) -> str:
    """Busca en internet. Intenta varias fuentes por si alguna falla."""
    maximo = max(1, min(int(max_resultados), 10))
    intentos = [("DuckDuckGo", lambda: _buscar_ddgs(consulta, maximo, noticias))]
    if not noticias:
        intentos.append(("DuckDuckGo HTML", lambda: _buscar_ddg_html(consulta, maximo)))
    intentos.append(("Wikipedia", lambda: _buscar_wikipedia(consulta, maximo)))

    errores = []
    for fuente, fn in intentos:
        try:
            res = fn()
            if res:
                lineas = [f"Resultados de {fuente} para: {consulta}\n"]
                for i, r in enumerate(res, 1):
                    fecha = f" ({r['fecha']})" if r.get("fecha") else ""
                    lineas.append(f"{i}. {r['titulo']}{fecha}\n   {r['url']}\n   {r['resumen'][:300]}")
                lineas.append("\nUsa leer_web con la URL para leer el contenido completo.")
                return "\n".join(lineas)
        except Exception as e:  # probamos la siguiente fuente
            errores.append(f"{fuente}: {type(e).__name__}")
    return "No encontré resultados. " + ("Fallos: " + ", ".join(errores) if errores else "Prueba otras palabras.")


def leer_web(url: str, max_caracteres: int = 6000) -> str:
    """Descarga una página y devuelve su texto limpio."""
    if not re.match(r"^https?://", url or "", flags=re.I):
        return "Error: solo se permiten URLs que empiecen por http:// o https://"
    try:
        contenido, tipo = _http_get(url)
    except Exception as e:
        return f"No pude abrir la página ({type(e).__name__}: {e}). Prueba con otra fuente."
    if "pdf" in tipo.lower():
        return "Es un PDF; no puedo leerlo directamente. Busca una versión HTML o el resumen del artículo."
    if "json" in tipo.lower() or "text/plain" in tipo.lower():
        return _recortar(contenido, int(max_caracteres))
    titulo, texto = html_a_texto(contenido)
    if len(texto) < 200:
        return f"La página ({titulo or url}) casi no tiene texto legible (puede necesitar JavaScript). Prueba otra fuente."
    return _recortar(f"TÍTULO: {titulo}\nURL: {url}\n\n{texto}", int(max_caracteres))


# =====================================================================
# Artículos académicos (OpenAlex: base de datos abierta con +250M de trabajos reales)
# =====================================================================

def _abstract(indice: dict | None, max_palabras: int = 70) -> str:
    if not indice:
        return ""
    posiciones = [(pos, palabra) for palabra, lista in indice.items() for pos in lista]
    palabras = [p for _, p in sorted(posiciones)]
    texto = " ".join(palabras[:max_palabras])
    return texto + ("..." if len(palabras) > max_palabras else "")


def _formatear_openalex(datos: dict, consulta: str) -> str:
    trabajos = datos.get("results", [])
    if not trabajos:
        return f"No encontré artículos para: {consulta}. Prueba términos en inglés o más generales."
    lineas = [f"Artículos académicos (OpenAlex) para: {consulta}\n"]
    for i, w in enumerate(trabajos, 1):
        autores = [a.get("author", {}).get("display_name", "") for a in w.get("authorships", [])[:3]]
        if len(w.get("authorships", [])) > 3:
            autores.append("et al.")
        fuente = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
        acceso = (w.get("open_access") or {}).get("oa_url") or ""
        doi = w.get("doi") or ""
        lineas.append(
            f"{i}. {w.get('display_name', 'Sin título')} ({w.get('publication_year', '?')})\n"
            f"   Autores: {', '.join(a for a in autores if a) or 'N/D'}\n"
            f"   Revista/fuente: {fuente or 'N/D'} · Citas: {w.get('cited_by_count', 0)}\n"
            f"   DOI: {doi or 'N/D'}" + (f"\n   Acceso abierto: {acceso}" if acceso else "") +
            (f"\n   Resumen: {_abstract(w.get('abstract_inverted_index'))}" if w.get("abstract_inverted_index") else "")
        )
    return "\n".join(lineas)


def buscar_articulos(consulta: str, max_resultados: int = 6, desde_anio: int | None = None,
                     orden: str = "relevancia") -> str:
    """Busca artículos científicos reales con autores, año, DOI y citas."""
    params = {"search": consulta, "per-page": max(1, min(int(max_resultados), 15))}
    filtros = []
    if desde_anio:
        filtros.append(f"from_publication_date:{int(desde_anio)}-01-01")
    if filtros:
        params["filter"] = ",".join(filtros)
    if orden == "citas":
        params["sort"] = "cited_by_count:desc"
    elif orden == "recientes":
        params["sort"] = "publication_date:desc"
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    try:
        datos = json.loads(_http_get(url, timeout=25)[0])
    except Exception as e:
        return f"No pude consultar OpenAlex ({type(e).__name__}). Intenta de nuevo o usa buscar_web."
    return _formatear_openalex(datos, consulta)


# =====================================================================
# Memoria (notas que duran entre sesiones)
# =====================================================================

def _archivo_notas() -> Path:
    MEMORIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEMORIA_DIR / "notas.json"


def _cargar_notas() -> list[dict]:
    f = _archivo_notas()
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def guardar_nota(tema: str, contenido: str) -> str:
    with _lock_memoria:
        notas = _cargar_notas()
        notas.append({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "tema": tema.strip(),
                      "contenido": contenido.strip()})
        _archivo_notas().write_text(json.dumps(notas, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Nota guardada en memoria (tema: {tema}). Total de notas: {len(notas)}"


def buscar_notas(consulta: str = "", max_resultados: int = 10) -> str:
    notas = _cargar_notas()
    if not notas:
        return "La memoria está vacía."
    if consulta.strip():
        palabras = [p for p in re.findall(r"\w+", consulta.lower()) if len(p) > 2]
        puntuadas = []
        for n in notas:
            texto = f"{n['tema']} {n['contenido']}".lower()
            puntos = sum(texto.count(p) for p in palabras)
            if puntos:
                puntuadas.append((puntos, n))
        notas = [n for _, n in sorted(puntuadas, key=lambda x: -x[0])]
        if not notas:
            return f"No hay notas sobre: {consulta}"
    else:
        notas = notas[::-1]  # las más recientes primero
    return "\n".join(f"- [{n['fecha']}] {n['tema']}: {n['contenido']}" for n in notas[:int(max_resultados)])


# =====================================================================
# Otras
# =====================================================================

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_actual() -> str:
    a = datetime.now()
    return f"{DIAS[a.weekday()]} {a.day} de {MESES[a.month - 1]} de {a.year}, {a:%H:%M} ({a:%Y-%m-%d})"


# =====================================================================
# Registro
# =====================================================================

def _esquema(props: dict, requeridos: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": requeridos or []}


HERRAMIENTAS = {
    "leer_archivo": {
        "fn": leer_archivo,
        "description": "Lee un archivo de texto del workspace.",
        "input_schema": _esquema({"ruta": {"type": "string", "description": "Ruta relativa al workspace"}}, ["ruta"]),
    },
    "escribir_archivo": {
        "fn": escribir_archivo,
        "description": "Crea o reemplaza un archivo en el workspace con el contenido COMPLETO.",
        "input_schema": _esquema({"ruta": {"type": "string"}, "contenido": {"type": "string"}}, ["ruta", "contenido"]),
    },
    "listar_archivos": {
        "fn": listar_archivos,
        "description": "Lista archivos y carpetas del workspace (recursivo).",
        "input_schema": _esquema({"ruta": {"type": "string", "description": "Carpeta, por defecto '.'"}}),
    },
    "ejecutar_comando": {
        "fn": ejecutar_comando,
        "description": "Ejecuta un comando de terminal dentro del workspace (pruebas, scripts, instalar paquetes).",
        "input_schema": _esquema({"comando": {"type": "string"},
                                  "timeout": {"type": "integer", "description": "Segundos, por defecto 120"}}, ["comando"]),
    },
    "buscar_web": {
        "fn": buscar_web,
        "description": "Busca en internet y devuelve títulos, URLs y resúmenes. Usa noticias=true para actualidad.",
        "input_schema": _esquema({"consulta": {"type": "string"},
                                  "max_resultados": {"type": "integer", "description": "1-10, por defecto 6"},
                                  "noticias": {"type": "boolean", "description": "true para buscar noticias recientes"}},
                                 ["consulta"]),
    },
    "leer_web": {
        "fn": leer_web,
        "description": "Abre una URL y devuelve el texto de la página para leerla a fondo.",
        "input_schema": _esquema({"url": {"type": "string"},
                                  "max_caracteres": {"type": "integer", "description": "Por defecto 6000"}}, ["url"]),
    },
    "buscar_articulos": {
        "fn": buscar_articulos,
        "description": ("Busca artículos científicos REALES (OpenAlex) con autores, año, revista, DOI, citas y resumen. "
                        "Funciona mejor con términos en inglés."),
        "input_schema": _esquema({"consulta": {"type": "string"},
                                  "max_resultados": {"type": "integer", "description": "1-15, por defecto 6"},
                                  "desde_anio": {"type": "integer", "description": "Solo publicados desde este año"},
                                  "orden": {"type": "string", "enum": ["relevancia", "citas", "recientes"]}},
                                 ["consulta"]),
    },
    "guardar_nota": {
        "fn": guardar_nota,
        "description": ("Guarda algo en la memoria permanente (preferencias del usuario, temas que estudia, "
                        "hallazgos importantes) para recordarlo en futuras sesiones."),
        "input_schema": _esquema({"tema": {"type": "string"}, "contenido": {"type": "string"}}, ["tema", "contenido"]),
    },
    "buscar_notas": {
        "fn": buscar_notas,
        "description": "Busca en la memoria permanente. Sin consulta devuelve las notas más recientes.",
        "input_schema": _esquema({"consulta": {"type": "string"},
                                  "max_resultados": {"type": "integer"}}),
    },
    "fecha_actual": {
        "fn": fecha_actual,
        "description": "Devuelve la fecha y hora actuales. Úsala antes de hablar de 'hoy', 'reciente' o 'este año'.",
        "input_schema": _esquema({}),
    },
}


def esquemas(nombres: list[str]) -> list[dict]:
    return [
        {"name": n, "description": HERRAMIENTAS[n]["description"], "input_schema": HERRAMIENTAS[n]["input_schema"]}
        for n in nombres
    ]


async def usar(nombre: str, args: dict) -> str:
    fn = HERRAMIENTAS[nombre]["fn"]
    # quita argumentos que la función no acepta (los modelos a veces inventan parámetros)
    validos = fn.__code__.co_varnames[:fn.__code__.co_argcount]
    args = {k: v for k, v in (args or {}).items() if k in validos and v is not None}
    return await asyncio.to_thread(fn, **args)

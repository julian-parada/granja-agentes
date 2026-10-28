"""Pruebas de las herramientas (sin internet)."""
import asyncio
import json

import pytest

import tools


# ---------- Archivos y seguridad ----------

def test_escribir_y_leer():
    assert "Guardado" in tools.escribir_archivo("carpeta/a.txt", "hola")
    assert tools.leer_archivo("carpeta/a.txt") == "hola"
    assert "carpeta/a.txt" in tools.listar_archivos()


def test_no_sale_del_workspace():
    with pytest.raises(ValueError):
        tools.leer_archivo("../../secreto.txt")
    with pytest.raises(ValueError):
        tools.escribir_archivo("../fuera.txt", "x")


@pytest.mark.parametrize("cmd", ["rm -rf /", "del /s /q C:\\", "format C:", "Remove-Item -Recurse C:\\", "shutdown /s"])
def test_comandos_peligrosos_bloqueados(cmd):
    assert tools.ejecutar_comando(cmd) == "Comando bloqueado por seguridad."


def test_ejecuta_comando_real():
    salida = tools.ejecutar_comando('python -c "print(2+2)"')
    assert "4" in salida and "código de salida: 0" in salida


def test_usar_ignora_argumentos_inventados():
    tools.escribir_archivo("b.txt", "contenido")
    r = asyncio.run(tools.usar("leer_archivo", {"ruta": "b.txt", "parametro_falso": 1}))
    assert r == "contenido"


# ---------- Web (parsers, sin red) ----------

def test_html_a_texto_limpia():
    html = """<html><head><title>Mi Página</title><style>.x{}</style></head>
    <body><nav>menú</nav><h1>Título</h1><p>Párrafo   uno.</p><script>alert(1)</script>
    <footer>pie</footer></body></html>"""
    titulo, texto = tools.html_a_texto(html)
    assert titulo == "Mi Página"
    assert "Párrafo uno." in texto and "Título" in texto
    assert "alert" not in texto and "menú" not in texto and "pie" not in texto


def test_parsear_duckduckgo():
    html = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fejemplo.com%2Fa&amp;rut=1">'
            'Ejemplo <b>uno</b></a><a class="result__snippet" href="x">Resumen &amp; más</a>'
            '<a class="result__a" href="https://otro.org/">Otro</a>')
    r = tools._parsear_ddg_html(html, 5)
    assert r[0] == {"titulo": "Ejemplo uno", "url": "https://ejemplo.com/a", "resumen": "Resumen & más"}
    assert r[1]["url"] == "https://otro.org/"


def test_buscar_web_usa_respaldo(monkeypatch):
    def falla(*a, **k):
        raise ConnectionError("sin red")
    monkeypatch.setattr(tools, "_buscar_ddgs", falla)
    monkeypatch.setattr(tools, "_buscar_ddg_html", falla)
    monkeypatch.setattr(tools, "_buscar_wikipedia",
                        lambda c, m: [{"titulo": "Python", "url": "https://es.wikipedia.org/wiki/Python", "resumen": "lenguaje"}])
    r = tools.buscar_web("python")
    assert "Wikipedia" in r and "https://es.wikipedia.org/wiki/Python" in r


def test_buscar_web_todo_falla(monkeypatch):
    def falla(*a, **k):
        raise ConnectionError()
    for f in ("_buscar_ddgs", "_buscar_ddg_html", "_buscar_wikipedia"):
        monkeypatch.setattr(tools, f, falla)
    assert "No encontré resultados" in tools.buscar_web("x")


def test_normalizar_url_con_tildes():
    assert tools._normalizar_url("https://es.wikipedia.org/wiki/Ocaña_(Colombia)") == \
        "https://es.wikipedia.org/wiki/Oca%C3%B1a_(Colombia)"
    assert tools._normalizar_url("https://x.com/buscar?q=educación virtual") == \
        "https://x.com/buscar?q=educaci%C3%B3n%20virtual"
    # una URL ya codificada no se daña
    assert tools._normalizar_url("https://x.com/a%20b") == "https://x.com/a%20b"


def test_leer_web_rechaza_esquemas_raros():
    assert "solo se permiten" in tools.leer_web("file:///C:/Windows/win.ini")


def test_leer_web_html(monkeypatch):
    html = "<html><title>T</title><body><p>" + "texto útil " * 50 + "</p></body></html>"
    monkeypatch.setattr(tools, "_http_get", lambda url, **k: (html, "text/html"))
    r = tools.leer_web("https://ejemplo.com")
    assert r.startswith("TÍTULO: T") and "texto útil" in r


# ---------- Artículos (OpenAlex) ----------

def test_formatear_openalex():
    datos = {"results": [{
        "display_name": "Deep learning", "publication_year": 2015, "cited_by_count": 50000,
        "doi": "https://doi.org/10.1038/nature14539",
        "authorships": [{"author": {"display_name": n}} for n in ["LeCun", "Bengio", "Hinton", "Otro"]],
        "primary_location": {"source": {"display_name": "Nature"}},
        "open_access": {"oa_url": None},
        "abstract_inverted_index": {"Deep": [0], "learning": [1], "allows": [2]},
    }]}
    r = tools._formatear_openalex(datos, "deep learning")
    assert "Deep learning (2015)" in r and "LeCun, Bengio, Hinton, et al." in r
    assert "Nature" in r and "10.1038/nature14539" in r and "Deep learning allows" in r


def test_openalex_sin_resultados():
    assert "No encontré artículos" in tools._formatear_openalex({"results": []}, "zzz")


def test_buscar_articulos_arma_url(monkeypatch):
    vistas = []

    def falso(url, **k):
        vistas.append(url)
        return json.dumps({"results": []}), "application/json"
    monkeypatch.setattr(tools, "_http_get", falso)
    tools.buscar_articulos("machine learning", desde_anio=2020, orden="citas")
    assert "from_publication_date%3A2020-01-01" in vistas[0] and "cited_by_count%3Adesc" in vistas[0]


# ---------- Memoria ----------

def test_memoria_guardar_y_buscar():
    tools.guardar_nota("preferencias", "Al usuario le gusta aprender con ejemplos de fútbol")
    tools.guardar_nota("estudio", "Está estudiando redes CCNA")
    assert "CCNA" in tools.buscar_notas("redes")
    assert "fútbol" in tools.buscar_notas("ejemplos")
    assert "No hay notas" in tools.buscar_notas("astronomía")
    assert "CCNA" in tools.buscar_notas()  # sin consulta: las más recientes


def test_fecha_actual():
    import re
    assert re.search(r"\d{4}-\d{2}-\d{2}", tools.fecha_actual())


def test_todas_las_herramientas_tienen_esquema_valido():
    for nombre, h in tools.HERRAMIENTAS.items():
        assert callable(h["fn"]) and h["description"]
        esq = h["input_schema"]
        assert esq["type"] == "object"
        for req in esq.get("required", []):
            assert req in esq["properties"], f"{nombre}: '{req}' requerido pero no definido"

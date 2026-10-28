"""El motor de cada agente: un loop que piensa → usa herramientas → repite hasta terminar.
Funciona con Anthropic (SDK propio) o con cualquier proveedor compatible con OpenAI
(Groq, Ollama, DeepSeek, OpenRouter).

Protecciones incluidas:
- Reintentos con espera ante errores temporales (límite de peticiones, servidor caído, tool call mal formada).
- Recorte de resultados viejos para no llenar el contexto.
- Si el agente "finge" el trabajo sin usar herramientas, se le insiste.
- Si responde vacío, se le pide el resumen.
- Si se acaban los pasos, entrega un resumen parcial en vez de nada.
"""
import asyncio
import json
import os
import platform
import sys
from datetime import datetime

import tools
from config import LOGS_DIR, MAX_PASOS, MAX_TOKENS, PROVEEDORES, REINTENTOS

COLORES = ["\033[96m", "\033[92m", "\033[93m", "\033[95m", "\033[94m", "\033[91m"]
RESET = "\033[0m"

_clientes = {}  # un cliente por proveedor, reutilizado

# Para que los agentes no usen comandos de Linux en Windows (o al revés)
if platform.system() == "Windows":
    ENTORNO = ("\n\nEntorno: Windows, terminal PowerShell/cmd. Para ejecutar Python usa `py archivo.py` "
               "y para instalar paquetes `py -m pip install paquete`. No uses comandos de Linux "
               "(chmod, ls, cat, rm, touch, grep).")
else:
    ENTORNO = f"\n\nEntorno: {platform.system()}. Para ejecutar Python usa `{sys.executable} archivo.py`."

REGLA_HERRAMIENTAS = (
    "\n\nIMPORTANTE: trabajas de verdad con herramientas reales. Para crear o cambiar archivos USA "
    "escribir_archivo; para ejecutar USA ejecutar_comando; para información USA las herramientas de búsqueda. "
    "Nunca escribas el código solo como texto ni inventes resultados: reporta únicamente lo que devolvieron "
    "las herramientas."
)
AVISO_SIN_HERRAMIENTAS = (
    "No usaste ninguna herramienta, así que no se hizo nada real. Haz la tarea llamando a las "
    "herramientas disponibles. No inventes resultados."
)
AVISO_VACIO = "Tu respuesta llegó vacía. Escribe ahora tu respuesta final completa para el usuario."
AVISO_SIN_PASOS = ("Se acabaron los pasos disponibles. Sin usar más herramientas, escribe un resumen de lo "
                   "que lograste, lo que quedó pendiente y cómo continuar.")

CODIGOS_REINTENTABLES = {408, 409, 425, 429, 500, 502, 503, 504, 529}


# =====================================================================
# Utilidades
# =====================================================================

def log_archivo(linea: str) -> None:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOGS_DIR / f"{datetime.now():%Y-%m-%d}.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%H:%M:%S} {linea}\n")
    except OSError:
        pass


def es_reintentable(e: Exception) -> bool:
    estado = getattr(e, "status_code", None)
    if estado in CODIGOS_REINTENTABLES:
        return True
    texto = str(e).lower()
    # Groq devuelve 400 cuando el modelo generó una llamada a herramienta mal formada: reintentar suele bastar
    if estado == 400 and ("tool_use_failed" in texto or "failed to call a function" in texto
                          or "tool call validation" in texto):
        return True
    nombre = type(e).__name__.lower()
    return any(k in nombre for k in ("ratelimit", "connection", "timeout", "overloaded", "internalserver"))


def tiempo_espera(e: Exception, intento: int) -> float:
    resp = getattr(e, "response", None)
    try:
        ra = float(resp.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        ra = None
    return min(ra if ra else 2 ** intento * 2, 60)


def explicar_error(e: Exception) -> str:
    """Convierte errores técnicos en un mensaje entendible."""
    estado = getattr(e, "status_code", None)
    texto = str(e)
    if estado == 401 or "api key" in texto.lower() or "authentication" in texto.lower():
        return "API key inválida o vencida. Revisa la key en tu .env."
    if estado == 404 and "model" in texto.lower():
        return f"El modelo no existe en ese proveedor. Revisa MODELO_* en tu .env.\nDetalle: {texto[:200]}"
    if estado == 429:
        return "Llegaste al límite de peticiones del plan gratis. Espera un rato o cambia de proveedor."
    if estado == 413:
        return "La petición fue demasiado grande para el proveedor. Baja MAX_TOKENS o pide tareas más pequeñas."
    if "connection" in type(e).__name__.lower():
        return "No hay conexión con el proveedor (¿internet caído u Ollama cerrado?)."
    return f"{type(e).__name__}: {texto[:300]}"


def compactar(mensajes: list, conservar: int = 6, limite: int = 1500) -> None:
    """Recorta resultados de herramientas viejos y largos para ahorrar contexto (modifica la lista)."""
    for m in mensajes[:-conservar] if len(mensajes) > conservar else []:
        if m.get("role") == "tool" and isinstance(m.get("content"), str) and len(m["content"]) > limite:
            m["content"] = m["content"][:limite] + "\n...[recortado para ahorrar contexto]"
        elif isinstance(m.get("content"), list):  # formato Anthropic
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result" \
                        and isinstance(b.get("content"), str) and len(b["content"]) > limite:
                    b["content"] = b["content"][:limite] + "\n...[recortado para ahorrar contexto]"


def _cliente(proveedor: str):
    if proveedor in _clientes:
        return _clientes[proveedor]
    if proveedor not in PROVEEDORES:
        raise ValueError(f"Proveedor '{proveedor}' no existe. Opciones: {', '.join(PROVEEDORES)}")
    cfg = PROVEEDORES[proveedor]
    key = os.getenv(cfg["key_env"]) if cfg["key_env"] else "ollama"
    if cfg["key_env"] and not key:
        raise ValueError(f"Falta {cfg['key_env']} en el .env para usar {proveedor}")

    if proveedor == "anthropic":
        from anthropic import AsyncAnthropic
        cli = AsyncAnthropic(api_key=key, max_retries=0)
    else:
        from openai import AsyncOpenAI
        cli = AsyncOpenAI(base_url=cfg["base_url"], api_key=key, timeout=600, max_retries=0)
    _clientes[proveedor] = cli
    return cli


# =====================================================================
# Agente
# =====================================================================

class Agente:
    def __init__(self, nombre, prompt, herramientas, proveedor, modelo="", extras=None,
                 exigir_herramientas=False):
        """
        herramientas: nombres de tools.HERRAMIENTAS
        extras: herramientas propias {nombre: (esquema, funcion_async)}
        exigir_herramientas: si True, no acepta una respuesta final sin haber usado herramientas
        """
        self.nombre = nombre
        self.prompt = prompt + ENTORNO
        self.proveedor = proveedor
        self.modelo = modelo or PROVEEDORES.get(proveedor, {}).get("modelo", "")
        if proveedor not in PROVEEDORES:
            raise ValueError(f"Proveedor '{proveedor}' no existe. Opciones: {', '.join(PROVEEDORES)}")
        if not self.modelo:
            raise ValueError(f"Define un modelo para {proveedor} en el .env")
        self.extras = extras or {}
        self.tools = tools.esquemas(herramientas) + [esq for esq, _ in self.extras.values()]
        self.exigir = exigir_herramientas
        self.color = COLORES[sum(map(ord, nombre)) % len(COLORES)]

    @property
    def sistema(self) -> str:
        return self.prompt + (REGLA_HERRAMIENTAS if self.exigir else "")

    def log(self, msg):
        print(f"{self.color}[{self.nombre}]{RESET} {msg}", flush=True)
        log_archivo(f"[{self.nombre}] {msg}")

    async def _llamar(self, crear):
        """Llama al modelo con reintentos. `crear` es una función que devuelve la corrutina."""
        for intento in range(REINTENTOS + 1):
            try:
                return await crear()
            except Exception as e:
                if intento >= REINTENTOS or not es_reintentable(e):
                    raise
                espera = tiempo_espera(e, intento)
                self.log(f"⏳ error temporal ({getattr(e, 'status_code', type(e).__name__)}), "
                         f"reintento {intento + 1}/{REINTENTOS} en {espera:.0f}s")
                await asyncio.sleep(espera)

    async def _usar(self, nombre, args):
        try:
            if nombre in self.extras:
                return str(await self.extras[nombre][1](**args)), False
            disponibles = [t["name"] for t in self.tools]
            if nombre not in disponibles:
                return f"Error: la herramienta '{nombre}' no existe. Disponibles: {', '.join(disponibles)}", True
            return str(await tools.usar(nombre, args)), False
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}", True

    async def ejecutar(self, tarea: str, historial: list | None = None) -> str:
        """historial: turnos previos [{'role': 'user'|'assistant', 'content': str}, ...]"""
        self.log(f"▶ ({self.proveedor}/{self.modelo}) {tarea[:100]}")
        historial = [dict(m) for m in (historial or [])]
        if self.proveedor == "anthropic":
            return await self._loop_anthropic(tarea, historial)
        return await self._loop_openai(tarea, historial)

    # ---------- Anthropic ----------
    async def _loop_anthropic(self, tarea, historial):
        cli = _cliente("anthropic")
        mensajes = historial + [{"role": "user", "content": tarea}]
        usadas, avisos_tools, avisos_vacio = False, 0, 0

        for _ in range(MAX_PASOS):
            compactar(mensajes)
            kwargs = dict(model=self.modelo, max_tokens=MAX_TOKENS, system=self.sistema, messages=mensajes)
            if self.tools:
                kwargs["tools"] = self.tools
            resp = await self._llamar(lambda: cli.messages.create(**kwargs))
            mensajes.append({"role": "assistant", "content": resp.content})
            texto = "".join(b.text for b in resp.content if b.type == "text")

            if resp.stop_reason != "tool_use":
                if self.exigir and not usadas and avisos_tools < 2:
                    avisos_tools += 1
                    self.log("↺ respondió sin usar herramientas, le pido que las use")
                    mensajes.append({"role": "user", "content": AVISO_SIN_HERRAMIENTAS})
                    continue
                if not texto.strip() and avisos_vacio < 2:
                    avisos_vacio += 1
                    self.log("↺ respuesta vacía, le pido la respuesta final")
                    mensajes.append({"role": "user", "content": AVISO_VACIO})
                    continue
                self.log("✔ terminó")
                return texto or "(el modelo no devolvió texto)"

            usadas = True
            resultados = []
            for b in resp.content:
                if b.type == "tool_use":
                    self.log(f"🔧 {b.name}({str(b.input)[:100]})")
                    salida, error = await self._usar(b.name, b.input)
                    resultados.append({"type": "tool_result", "tool_use_id": b.id,
                                       "content": salida, "is_error": error})
            mensajes.append({"role": "user", "content": resultados})

        self.log("⚠ alcanzó el límite de pasos, pido resumen parcial")
        mensajes.append({"role": "user", "content": AVISO_SIN_PASOS})
        compactar(mensajes)
        kwargs = dict(model=self.modelo, max_tokens=MAX_TOKENS, system=self.sistema, messages=mensajes)
        if self.tools:  # el historial tiene tool_use, así que hay que declarar las tools pero prohibir usarlas
            kwargs.update(tools=self.tools, tool_choice={"type": "none"})
        resp = await self._llamar(lambda: cli.messages.create(**kwargs))
        return "".join(b.text for b in resp.content if b.type == "text") or "No terminé: alcancé el límite de pasos."

    # ---------- Formato OpenAI (Groq, Ollama, DeepSeek, OpenRouter) ----------
    async def _loop_openai(self, tarea, historial):
        cli = _cliente(self.proveedor)
        herramientas = [
            {"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in self.tools
        ]
        mensajes = [{"role": "system", "content": self.sistema}] + historial + [{"role": "user", "content": tarea}]
        usadas, avisos_tools, avisos_vacio = False, 0, 0

        for _ in range(MAX_PASOS):
            compactar(mensajes)
            kwargs = dict(model=self.modelo, max_tokens=MAX_TOKENS, messages=mensajes)
            if herramientas:
                kwargs["tools"] = herramientas
            resp = await self._llamar(lambda: cli.chat.completions.create(**kwargs))
            m = resp.choices[0].message
            contenido = m.content or ""
            asistente = {"role": "assistant", "content": contenido}
            if m.tool_calls:
                asistente["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                    for tc in m.tool_calls
                ]
            mensajes.append(asistente)

            if not m.tool_calls:
                if self.exigir and not usadas and avisos_tools < 2:
                    avisos_tools += 1
                    self.log("↺ respondió sin usar herramientas, le pido que las use")
                    mensajes.append({"role": "user", "content": AVISO_SIN_HERRAMIENTAS})
                    continue
                if not contenido.strip() and avisos_vacio < 2:
                    avisos_vacio += 1
                    self.log("↺ respuesta vacía, le pido la respuesta final")
                    mensajes.append({"role": "user", "content": AVISO_VACIO})
                    continue
                self.log("✔ terminó")
                return contenido or "(el modelo no devolvió texto)"

            usadas = True
            for tc in m.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    if not isinstance(args, dict):
                        raise json.JSONDecodeError("no es objeto", "", 0)
                    self.log(f"🔧 {tc.function.name}({str(args)[:100]})")
                    salida, _ = await self._usar(tc.function.name, args)
                except json.JSONDecodeError:
                    # los modelos pequeños a veces mandan JSON roto: se lo decimos para que corrija
                    salida = "Error: los argumentos no son JSON válido. Vuelve a intentarlo."
                mensajes.append({"role": "tool", "tool_call_id": tc.id, "content": salida})

        self.log("⚠ alcanzó el límite de pasos, pido resumen parcial")
        mensajes.append({"role": "user", "content": AVISO_SIN_PASOS})
        compactar(mensajes)
        kwargs = dict(model=self.modelo, max_tokens=MAX_TOKENS, messages=mensajes)
        if herramientas:
            kwargs.update(tools=herramientas, tool_choice="none")
        resp = await self._llamar(lambda: cli.chat.completions.create(**kwargs))
        return resp.choices[0].message.content or "No terminé: alcancé el límite de pasos."

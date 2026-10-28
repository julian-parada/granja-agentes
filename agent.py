"""El motor de cada agente: un loop que piensa → usa herramientas → repite hasta terminar.
Funciona con Anthropic (SDK propio) o con cualquier proveedor compatible con OpenAI
(Ollama, DeepSeek, Groq, OpenRouter).
"""
import json
import os
import platform
import sys

import tools
from config import MAX_PASOS, MAX_TOKENS, PROVEEDORES

COLORES = ["\033[96m", "\033[92m", "\033[93m", "\033[95m", "\033[94m", "\033[91m"]
RESET = "\033[0m"

_clientes = {}  # un cliente por proveedor, reutilizado

# Para que los agentes no usen comandos de Linux en Windows (o al revés)
if platform.system() == "Windows":
    ENTORNO = ("\n\nEntorno: Windows, terminal PowerShell/cmd. Para ejecutar Python usa `py archivo.py`. "
               "No uses comandos de Linux (chmod, ls, cat, rm, touch); usa sus equivalentes de Windows o no los uses.")
else:
    ENTORNO = f"\n\nEntorno: {platform.system()}. Para ejecutar Python usa `{sys.executable} archivo.py`."

REGLA_HERRAMIENTAS = (
    "\n\nIMPORTANTE: trabajas de verdad sobre archivos reales. Para crear o cambiar archivos "
    "USA la herramienta escribir_archivo; para ejecutar USA ejecutar_comando. Nunca escribas el "
    "código solo como texto ni inventes resultados: reporta únicamente lo que devolvieron las herramientas."
)
AVISO_SIN_HERRAMIENTAS = (
    "No usaste ninguna herramienta, así que no se hizo nada real. Haz la tarea llamando a las "
    "herramientas (por ejemplo escribir_archivo y luego ejecutar_comando). No inventes resultados."
)


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
        cli = AsyncAnthropic(api_key=key)
    else:
        from openai import AsyncOpenAI
        cli = AsyncOpenAI(base_url=cfg["base_url"], api_key=key, timeout=600)
    _clientes[proveedor] = cli
    return cli


class Agente:
    def __init__(self, nombre, prompt, herramientas, proveedor, modelo="", extras=None):
        """extras: herramientas propias {nombre: (esquema, funcion_async)}"""
        self.nombre = nombre
        self.prompt = prompt + ENTORNO
        self.proveedor = proveedor
        self.modelo = modelo or PROVEEDORES[proveedor]["modelo"]
        if not self.modelo:
            raise ValueError(f"Define un modelo para {proveedor} en el .env")
        self.extras = extras or {}
        self.tools = tools.esquemas(herramientas) + [esq for esq, _ in self.extras.values()]
        self.color = COLORES[sum(map(ord, nombre)) % len(COLORES)]

    def log(self, msg):
        print(f"{self.color}[{self.nombre}]{RESET} {msg}")

    async def _usar(self, nombre, args):
        try:
            if nombre in self.extras:
                return str(await self.extras[nombre][1](**args)), False
            if nombre not in tools.HERRAMIENTAS:
                return f"Error: la herramienta '{nombre}' no existe", True
            return str(await tools.usar(nombre, args)), False
        except Exception as e:
            return f"Error: {e}", True

    async def ejecutar(self, tarea: str) -> str:
        self.log(f"▶ ({self.proveedor}/{self.modelo}) {tarea[:100]}")
        if self.proveedor == "anthropic":
            return await self._loop_anthropic(tarea)
        return await self._loop_openai(tarea)

    # ---------- Anthropic ----------
    async def _loop_anthropic(self, tarea):
        cli = _cliente("anthropic")
        mensajes = [{"role": "user", "content": tarea}]
        for _ in range(MAX_PASOS):
            resp = await cli.messages.create(
                model=self.modelo, max_tokens=MAX_TOKENS, system=self.prompt,
                tools=self.tools, messages=mensajes,
            )
            mensajes.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                self.log("✔ terminó")
                return "".join(b.text for b in resp.content if b.type == "text")

            resultados = []
            for b in resp.content:
                if b.type == "tool_use":
                    self.log(f"🔧 {b.name}({str(b.input)[:100]})")
                    salida, error = await self._usar(b.name, b.input)
                    resultados.append({"type": "tool_result", "tool_use_id": b.id,
                                       "content": salida, "is_error": error})
            mensajes.append({"role": "user", "content": resultados})
        return self._sin_pasos()

    # ---------- Formato OpenAI (Ollama, DeepSeek, Groq, OpenRouter) ----------
    async def _loop_openai(self, tarea):
        cli = _cliente(self.proveedor)
        herramientas = [
            {"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in self.tools
        ]
        # la regla de "usa herramientas" solo aplica a agentes que escriben archivos (no al orquestador)
        trabajador = any(t["name"] == "escribir_archivo" for t in self.tools)
        sistema = self.prompt + (REGLA_HERRAMIENTAS if trabajador else "")
        mensajes = [{"role": "system", "content": sistema},
                    {"role": "user", "content": tarea}]
        uso_herramientas = False
        avisos = 0

        for _ in range(MAX_PASOS):
            resp = await cli.chat.completions.create(
                model=self.modelo, max_tokens=MAX_TOKENS,
                messages=mensajes, tools=herramientas,
            )
            m = resp.choices[0].message
            asistente = {"role": "assistant", "content": m.content or ""}
            if m.tool_calls:
                uso_herramientas = True
                asistente["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                    for tc in m.tool_calls
                ]
            mensajes.append(asistente)

            # Modelos pequeños a veces "fingen" el trabajo sin usar herramientas: los obligamos
            if not m.tool_calls and not uso_herramientas and trabajador and avisos < 2:
                avisos += 1
                self.log("↺ respondió sin usar herramientas, le pido que las use")
                mensajes.append({"role": "user", "content": AVISO_SIN_HERRAMIENTAS})
                continue

            # Algunos modelos (gpt-oss) terminan con la respuesta vacía: le pedimos el resumen
            if not m.tool_calls and not (m.content or "").strip() and avisos < 3:
                avisos += 1
                self.log("↺ respuesta vacía, le pido el resumen final")
                mensajes.append({"role": "user", "content": "Tu respuesta llegó vacía. Escribe ahora tu resumen final de lo que se hizo y su resultado."})
                continue

            if not m.tool_calls:
                self.log("✔ terminó")
                return m.content or "(el modelo no devolvió texto)"

            for tc in m.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    self.log(f"🔧 {tc.function.name}({str(args)[:100]})")
                    salida, _ = await self._usar(tc.function.name, args)
                except json.JSONDecodeError:
                    # los modelos pequeños a veces mandan JSON roto: se lo decimos para que corrija
                    salida = "Error: los argumentos no son JSON válido. Vuelve a intentarlo."
                mensajes.append({"role": "tool", "tool_call_id": tc.id, "content": salida})
        return self._sin_pasos()

    def _sin_pasos(self):
        self.log("⚠ alcanzó el límite de pasos")
        return "No terminé: alcancé el límite de pasos (sube MAX_PASOS en .env si hace falta)."

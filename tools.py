"""Herramientas que los agentes pueden usar. Para agregar una nueva:
1. Escribe la función.
2. Regístrala en HERRAMIENTAS con su descripción y esquema.
3. Agrega su nombre a la lista de herramientas del agente en agents.py.
"""
import asyncio
import subprocess
import threading
from pathlib import Path

from config import CONFIRMAR_COMANDOS, WORKSPACE

_lock_consola = threading.Lock()  # para que dos agentes no pregunten a la vez

COMANDOS_BLOQUEADOS = [
    "rm -rf", "rmdir /s", "del /s", "del /f", "format ", "shutdown",
    "mkfs", "diskpart", "reg delete", ":(){",
]


def _ruta_segura(ruta: str) -> Path:
    p = (WORKSPACE / ruta).resolve()
    if p != WORKSPACE and WORKSPACE not in p.parents:
        raise ValueError(f"Ruta fuera del workspace: {ruta}")
    return p


def _recortar(texto: str, limite: int = 15000) -> str:
    return texto if len(texto) <= limite else texto[:limite] + "\n...[recortado]"


# ---------- Herramientas ----------

def leer_archivo(ruta: str) -> str:
    return _recortar(_ruta_segura(ruta).read_text(encoding="utf-8", errors="replace"))


def escribir_archivo(ruta: str, contenido: str) -> str:
    p = _ruta_segura(ruta)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenido, encoding="utf-8")
    return f"Guardado {ruta} ({len(contenido)} caracteres)"


def listar_archivos(ruta: str = ".") -> str:
    base = _ruta_segura(ruta)
    ignorar = {".git", "node_modules", "__pycache__", ".venv", "vendor"}
    salida = []
    for p in sorted(base.rglob("*")):
        if any(parte in ignorar for parte in p.parts):
            continue
        salida.append(str(p.relative_to(WORKSPACE)) + ("/" if p.is_dir() else ""))
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
            return "El usuario rechazó el comando."
    try:
        r = subprocess.run(
            comando, shell=True, cwd=WORKSPACE,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return _recortar(f"código de salida: {r.returncode}\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}")
    except subprocess.TimeoutExpired:
        return f"El comando superó {timeout}s y se detuvo."


# ---------- Registro ----------

HERRAMIENTAS = {
    "leer_archivo": {
        "fn": leer_archivo,
        "description": "Lee un archivo de texto del workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"ruta": {"type": "string", "description": "Ruta relativa al workspace"}},
            "required": ["ruta"],
        },
    },
    "escribir_archivo": {
        "fn": escribir_archivo,
        "description": "Crea o reemplaza un archivo en el workspace con el contenido completo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ruta": {"type": "string"},
                "contenido": {"type": "string"},
            },
            "required": ["ruta", "contenido"],
        },
    },
    "listar_archivos": {
        "fn": listar_archivos,
        "description": "Lista archivos y carpetas del workspace (recursivo).",
        "input_schema": {
            "type": "object",
            "properties": {"ruta": {"type": "string", "default": "."}},
        },
    },
    "ejecutar_comando": {
        "fn": ejecutar_comando,
        "description": "Ejecuta un comando de terminal dentro del workspace (tests, scripts, instalar paquetes).",
        "input_schema": {
            "type": "object",
            "properties": {
                "comando": {"type": "string"},
                "timeout": {"type": "integer", "default": 120},
            },
            "required": ["comando"],
        },
    },
}


def esquemas(nombres: list[str]) -> list[dict]:
    return [
        {"name": n, "description": HERRAMIENTAS[n]["description"], "input_schema": HERRAMIENTAS[n]["input_schema"]}
        for n in nombres
    ]


async def usar(nombre: str, args: dict) -> str:
    return await asyncio.to_thread(HERRAMIENTAS[nombre]["fn"], **args)

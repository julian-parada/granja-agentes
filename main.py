"""Punto de entrada.

Uso:
  py main.py                               → chat con el orquestador (recuerda la conversación)
  py main.py "investiga X"                 → una sola orden al orquestador
  py main.py --agente tutor                → chat directo con un agente (ideal para estudiar)
  py main.py --agente tutor "explícame X"  → una sola orden a un agente
  py main.py --lista                       → ver agentes disponibles

Comandos dentro del chat:  /nuevo (olvida la conversación) · /agentes · /memoria · /salir
"""
import asyncio
import sys

from agent import explicar_error, log_archivo
from agents import AGENTES
from config import MAX_HISTORIAL, WORKSPACE
from orchestrator import crear_agente, crear_orquestador
from tools import buscar_notas

if hasattr(sys.stdout, "reconfigure"):  # emojis y tildes en la consola de Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def listar():
    for n, c in AGENTES.items():
        print(f"• {n}: {c['descripcion']}")


def _crear(nombre):
    return crear_orquestador() if nombre is None else crear_agente(nombre)


async def una_orden(nombre, orden):
    log_archivo(f"=== ORDEN ({nombre or 'orquestador'}): {orden}")
    try:
        print("\n" + await _crear(nombre).ejecutar(orden))
    except Exception as e:
        print(f"\n❌ {explicar_error(e)}")


async def chat(nombre=None):
    quien = nombre or "orquestador"
    print(f"🤖 Granja de agentes · hablando con: {quien} · workspace: {WORKSPACE}")
    print("   Comandos: /nuevo · /agentes · /memoria · /salir\n")
    historial = []
    while True:
        try:
            orden = input("Tú > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not orden:
            continue
        cmd = orden.lower()
        if cmd in {"/salir", "salir", "exit", "q"}:
            break
        if cmd == "/nuevo":
            historial = []
            print("🧹 Conversación reiniciada.\n")
            continue
        if cmd == "/agentes":
            listar()
            print()
            continue
        if cmd == "/memoria":
            print(buscar_notas() + "\n")
            continue

        log_archivo(f"=== CHAT ({quien}): {orden}")
        try:
            respuesta = await _crear(nombre).ejecutar(orden, historial)
        except KeyboardInterrupt:
            print("\n⏹ Cancelado.\n")
            continue
        except Exception as e:
            print(f"\n❌ {explicar_error(e)}\n")
            continue
        print(f"\n{respuesta}\n")
        historial += [{"role": "user", "content": orden}, {"role": "assistant", "content": respuesta}]
        historial = historial[-MAX_HISTORIAL * 2:]


async def main():
    args = sys.argv[1:]

    if args and args[0] in {"--lista", "-l"}:
        listar()
        return

    if args and args[0] in {"--agente", "-a"}:
        if len(args) < 2 or args[1] not in AGENTES:
            print(f"Agente no válido. Disponibles: {', '.join(AGENTES)}")
            return
        if len(args) == 2:
            await chat(args[1])
        else:
            await una_orden(args[1], " ".join(args[2:]))
        return

    if args:
        await una_orden(None, " ".join(args))
    else:
        await chat()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Hasta luego.")

"""Punto de entrada.

Uso:
  python main.py                              → modo chat con el orquestador
  python main.py "crea una API de tareas"     → una sola orden al orquestador
  python main.py --agente tester "prueba x"   → hablarle directo a un agente
  python main.py --lista                      → ver agentes disponibles
"""
import asyncio
import sys

from agents import AGENTES
from config import WORKSPACE
from orchestrator import correr_agente, crear_orquestador


async def main():
    args = sys.argv[1:]

    if args and args[0] == "--lista":
        for n, c in AGENTES.items():
            print(f"• {n}: {c['descripcion']}")
        return

    if len(args) >= 3 and args[0] == "--agente":
        nombre, tarea = args[1], " ".join(args[2:])
        if nombre not in AGENTES:
            print(f"Agente '{nombre}' no existe. Usa --lista.")
            return
        print("\n" + await correr_agente(nombre, tarea))
        return

    if args:
        print("\n" + await crear_orquestador().ejecutar(" ".join(args)))
        return

    print(f"🤖 Granja de agentes lista · workspace: {WORKSPACE}")
    print(f"   Agentes: {', '.join(AGENTES)} · escribe 'salir' para terminar\n")
    while True:
        orden = input("Tú > ").strip()
        if orden.lower() in {"salir", "exit", "q"}:
            break
        if orden:
            print("\n" + await crear_orquestador().ejecutar(orden) + "\n")


if __name__ == "__main__":
    asyncio.run(main())

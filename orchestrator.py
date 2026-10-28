"""El jefe: recibe tu pedido, lo divide y lo reparte entre los agentes (en paralelo)."""
import asyncio

from agent import Agente
from agents import AGENTES
from config import (MAX_PARALELO, MODELO_AGENTES, MODELO_ORQUESTADOR,
                    PROVEEDOR_AGENTES, PROVEEDOR_ORQUESTADOR)

_semaforo = asyncio.Semaphore(MAX_PARALELO)


async def correr_agente(nombre: str, tarea: str) -> str:
    async with _semaforo:
        cfg = AGENTES[nombre]
        proveedor = cfg.get("proveedor", PROVEEDOR_AGENTES)
        # si el agente no fija modelo: usa MODELO_AGENTES solo si es el proveedor por defecto
        modelo = cfg.get("modelo") or (MODELO_AGENTES if proveedor == PROVEEDOR_AGENTES else "")
        agente = Agente(nombre, cfg["prompt"], cfg["herramientas"], proveedor, modelo)
        return await agente.ejecutar(tarea)


async def delegar(tareas: list[dict]) -> str:
    """Corre varias tareas a la vez y junta los resultados."""
    resultados = await asyncio.gather(
        *(correr_agente(t["agente"], t["tarea"]) for t in tareas),
        return_exceptions=True,
    )
    partes = []
    for t, r in zip(tareas, resultados):
        estado = f"ERROR: {r}" if isinstance(r, Exception) else r
        partes.append(f"### {t['agente']}\nTarea: {t['tarea']}\nResultado:\n{estado}")
    return "\n\n".join(partes)


ESQUEMA_DELEGAR = {
    "name": "delegar",
    "description": (
        "Envía tareas a uno o varios agentes. Las tareas de una misma llamada corren EN PARALELO, "
        "así que solo agrupa las que no dependen entre sí. Si una depende de otra, haz llamadas separadas."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tareas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "agente": {"type": "string", "enum": list(AGENTES)},
                        "tarea": {"type": "string", "description": "Instrucción completa y autosuficiente"},
                    },
                    "required": ["agente", "tarea"],
                },
            }
        },
        "required": ["tareas"],
    },
}


def crear_orquestador() -> Agente:
    equipo = "\n".join(f"- {n}: {c['descripcion']}" for n, c in AGENTES.items())
    prompt = (
        "Eres el orquestador de un equipo de agentes de IA. No haces el trabajo tú mismo: "
        "lo divides en tareas claras y las delegas con la herramienta `delegar`.\n\n"
        f"Tu equipo:\n{equipo}\n\n"
        "Reglas:\n"
        "1. Revisa primero el workspace si la tarea involucra archivos.\n"
        "2. Cada tarea debe ser autosuficiente (los agentes no ven esta conversación).\n"
        "3. Paraleliza lo independiente; encadena lo dependiente (ej: programador → tester → revisor).\n"
        "4. Si un agente reporta fallas, vuelve a delegar la corrección.\n"
        "5. Cumple TODAS las partes del pedido. Antes de terminar, repasa el pedido original punto por punto "
        "y delega lo que falte (por ejemplo, si piden revisión, llama al revisor).\n"
        "6. Al final da un resumen corto en español: qué hizo cada agente y el resultado real "
        "(salida de pruebas, errores encontrados)."
    )
    return Agente(
        "orquestador", prompt, ["listar_archivos", "leer_archivo"],
        PROVEEDOR_ORQUESTADOR, MODELO_ORQUESTADOR,
        extras={"delegar": (ESQUEMA_DELEGAR, delegar)},
    )

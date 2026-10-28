"""El jefe: conversa contigo, decide si responde él mismo o reparte el trabajo entre los agentes."""
import asyncio

from agent import Agente
from agents import AGENTES
from config import (MAX_PARALELO, MODELO_AGENTES, MODELO_ORQUESTADOR,
                    PROVEEDOR_AGENTES, PROVEEDOR_ORQUESTADOR)

_semaforos = {}  # uno por event loop (evita errores al correr varias veces)


def _semaforo() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    if loop not in _semaforos:
        _semaforos[loop] = asyncio.Semaphore(MAX_PARALELO)
    return _semaforos[loop]


def crear_agente(nombre: str) -> Agente:
    if nombre not in AGENTES:
        raise ValueError(f"El agente '{nombre}' no existe. Disponibles: {', '.join(AGENTES)}")
    cfg = AGENTES[nombre]
    proveedor = cfg.get("proveedor", PROVEEDOR_AGENTES)
    # si el agente no fija modelo: usa MODELO_AGENTES solo si es el proveedor por defecto
    modelo = cfg.get("modelo") or (MODELO_AGENTES if proveedor == PROVEEDOR_AGENTES else "")
    return Agente(nombre, cfg["prompt"], cfg["herramientas"], proveedor, modelo,
                  exigir_herramientas=cfg.get("exigir", False))


async def correr_agente(nombre: str, tarea: str) -> str:
    async with _semaforo():
        return await crear_agente(nombre).ejecutar(tarea)


async def delegar(tareas: list[dict] | None = None) -> str:
    """Corre varias tareas a la vez y junta los resultados."""
    if not tareas or not isinstance(tareas, list):
        return "Error: debes enviar una lista 'tareas' con objetos {agente, tarea}."
    validas, errores = [], []
    for t in tareas:
        if not isinstance(t, dict) or not t.get("agente") or not t.get("tarea"):
            errores.append(f"Tarea mal formada: {t}")
        elif t["agente"] not in AGENTES:
            errores.append(f"El agente '{t['agente']}' no existe. Disponibles: {', '.join(AGENTES)}")
        else:
            validas.append(t)

    resultados = await asyncio.gather(
        *(correr_agente(t["agente"], t["tarea"]) for t in validas),
        return_exceptions=True,
    )
    partes = []
    for t, r in zip(validas, resultados):
        estado = f"ERROR: {type(r).__name__}: {r}" if isinstance(r, Exception) else r
        partes.append(f"### {t['agente']}\nTarea: {t['tarea']}\nResultado:\n{estado}")
    partes += [f"### ERROR\n{e}" for e in errores]
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
                        "tarea": {"type": "string",
                                  "description": "Instrucción completa y autosuficiente (el agente no ve la conversación)"},
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
        "Eres el coordinador de un equipo de agentes de IA y el asistente principal del usuario. "
        "Hablas en español, en tono cercano y directo.\n\n"
        f"Tu equipo:\n{equipo}\n\n"
        "Cómo decides:\n"
        "A) Responde TÚ MISMO, sin delegar, cuando sea conversación, una duda rápida o una explicación corta que "
        "puedas dar con seguridad.\n"
        "B) DELEGA con la herramienta `delegar` cuando haya que crear o cambiar archivos, ejecutar código, investigar "
        "con fuentes, buscar artículos, dar información actual, hacer material de estudio o un texto largo.\n\n"
        "Reglas al delegar:\n"
        "1. Si la tarea involucra archivos existentes, revisa primero el workspace.\n"
        "2. Cada tarea debe ser autosuficiente: incluye todo el contexto necesario (el agente no ve esta conversación, "
        "ni las preferencias del usuario: pásaselas).\n"
        "3. Paraleliza lo independiente; encadena lo dependiente (ej: programador → tester → revisor; "
        "investigador → redactor).\n"
        "4. Si un agente reporta fallas, vuelve a delegar la corrección (máximo 2 intentos por problema).\n"
        "5. Cumple TODAS las partes del pedido. Antes de terminar, repasa el pedido original punto por punto "
        "y delega lo que falte.\n\n"
        "Respuesta final:\n"
        "- Entrega el resultado completo, no solo 'se hizo'. Para investigaciones: los hallazgos y las fuentes. "
        "Para código: qué se creó, resultado de las pruebas y cómo usarlo. Para estudio: el material o dónde quedó.\n"
        "- Nunca inventes información que los agentes no reportaron.\n\n"
        "Memoria: al empezar temas personales o de estudio, consulta buscar_notas. Cuando el usuario cuente "
        "preferencias, metas o intereses duraderos, guárdalos con guardar_nota."
    )
    return Agente(
        "orquestador", prompt, ["listar_archivos", "leer_archivo", "buscar_notas", "guardar_nota", "fecha_actual"],
        PROVEEDOR_ORQUESTADOR, MODELO_ORQUESTADOR,
        extras={"delegar": (ESQUEMA_DELEGAR, delegar)},
    )

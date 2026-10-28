"""Pruebas del motor de agentes con un modelo falso."""
import asyncio

import agent
from agents import AGENTES
from fakes import ErrorAPI, ModeloFalso, respuesta
from orchestrator import crear_agente


def _correr(nombre, tarea, modelo, historial=None):
    agent._clientes["ollama"] = modelo
    return asyncio.run(crear_agente(nombre).ejecutar(tarea, historial))


def test_flujo_normal_con_herramientas():
    modelo = ModeloFalso([
        respuesta(llamadas=[("escribir_archivo", {"ruta": "x.py", "contenido": "print(1)"})]),
        respuesta(llamadas=[("ejecutar_comando", {"comando": 'python x.py'})]),
        respuesta("Creé x.py y lo ejecuté: imprime 1"),
    ])
    assert "imprime 1" in _correr("programador", "crea x.py", modelo)
    resultado_cmd = modelo.llamadas[2]["messages"][-1]["content"]
    assert "código de salida: 0" in resultado_cmd and "1" in resultado_cmd


def test_obliga_a_usar_herramientas_si_finge():
    modelo = ModeloFalso([
        respuesta("```python\nprint(1)```  ya lo hice, salida: 1"),
        respuesta(llamadas=[("escribir_archivo", {"ruta": "y.py", "contenido": "print(1)"})]),
        respuesta("hecho de verdad"),
    ])
    assert _correr("programador", "crea y.py", modelo) == "hecho de verdad"
    assert "No usaste ninguna herramienta" in modelo.llamadas[1]["messages"][-1]["content"]


def test_tutor_puede_responder_sin_herramientas():
    modelo = ModeloFalso([respuesta("Una variable es como una caja con etiqueta...")])
    assert "caja" in _correr("tutor", "qué es una variable", modelo)
    assert len(modelo.llamadas) == 1


def test_respuesta_vacia_pide_resumen():
    modelo = ModeloFalso([
        respuesta(llamadas=[("listar_archivos", {})]),
        respuesta(""),
        respuesta("resumen final"),
    ])
    assert _correr("revisor", "revisa", modelo) == "resumen final"


def test_json_roto_se_corrige():
    modelo = ModeloFalso([
        respuesta(llamadas=[("leer_archivo", "{roto")]),
        respuesta(llamadas=[("listar_archivos", {})]),
        respuesta("ok"),
    ])
    assert _correr("revisor", "revisa", modelo) == "ok"
    assert "no son JSON válido" in modelo.llamadas[1]["messages"][-1]["content"]


def test_herramienta_inexistente_no_rompe():
    modelo = ModeloFalso([
        respuesta(llamadas=[("borrar_todo", {})]),
        respuesta(llamadas=[("listar_archivos", {})]),
        respuesta("ok"),
    ])
    assert _correr("revisor", "revisa", modelo) == "ok"
    assert "no existe" in modelo.llamadas[1]["messages"][-1]["content"]


def test_reintenta_ante_limite_de_peticiones():
    modelo = ModeloFalso([
        ErrorAPI(429, "rate limit"),
        ErrorAPI(400, "tool_use_failed: Failed to call a function"),
        respuesta("Una función es un bloque reutilizable"),
    ])
    assert "función" in _correr("tutor", "qué es una función", modelo)


def test_no_reintenta_errores_permanentes():
    modelo = ModeloFalso([ErrorAPI(401, "invalid api key")])
    try:
        _correr("tutor", "hola", modelo)
        assert False, "debió lanzar error"
    except ErrorAPI as e:
        assert "API key" in agent.explicar_error(e)
    assert len(modelo.llamadas) == 1


def test_limite_de_pasos_da_resumen_parcial():
    def siempre_lista(mensajes, kwargs):
        if kwargs.get("tool_choice") == "none":
            return respuesta("Resumen parcial: revisé archivos, falta terminar")
        return respuesta(llamadas=[("listar_archivos", {})])
    r = _correr("revisor", "revisa", ModeloFalso(siempre_lista))
    assert r.startswith("Resumen parcial")


def test_historial_se_envia_al_modelo():
    modelo = ModeloFalso([respuesta("Te llamas Julian")])
    historial = [{"role": "user", "content": "me llamo Julian"}, {"role": "assistant", "content": "¡Hola Julian!"}]
    assert _correr("tutor", "¿cómo me llamo?", modelo, historial) == "Te llamas Julian"
    enviados = modelo.llamadas[0]["messages"]
    assert enviados[1]["content"] == "me llamo Julian" and enviados[-1]["content"] == "¿cómo me llamo?"


def test_compactar_recorta_resultados_viejos():
    mensajes = [{"role": "tool", "content": "x" * 5000}] + [{"role": "user", "content": "y"}] * 7
    agent.compactar(mensajes)
    assert len(mensajes[0]["content"]) < 2000
    mensajes_anthropic = [{"role": "user", "content": [{"type": "tool_result", "content": "z" * 5000}]}] + \
                         [{"role": "user", "content": "y"}] * 7
    agent.compactar(mensajes_anthropic)
    assert len(mensajes_anthropic[0]["content"][0]["content"]) < 2000


def test_todos_los_agentes_se_crean():
    for nombre, cfg in AGENTES.items():
        a = crear_agente(nombre)
        assert a.tools, f"{nombre} no tiene herramientas"
        assert cfg["descripcion"] and "Nunca inventes" in a.prompt

"""Pruebas del orquestador y la delegación."""
import asyncio
import json

import agent
from fakes import ModeloFalso, respuesta
from orchestrator import crear_orquestador, delegar


def test_orquestador_tiene_delegar():
    nombres = [t["name"] for t in crear_orquestador().tools]
    assert "delegar" in nombres and "buscar_notas" in nombres


def test_delegar_agente_inexistente():
    r = asyncio.run(delegar([{"agente": "hacker", "tarea": "x"}]))
    assert "no existe" in r


def test_delegar_sin_tareas():
    assert "Error" in asyncio.run(delegar([]))
    assert "Error" in asyncio.run(delegar(None))


def test_orquestador_responde_directo_en_conversacion():
    agent._clientes["ollama"] = ModeloFalso([respuesta("¡Hola! ¿En qué te ayudo?")])
    assert "Hola" in asyncio.run(crear_orquestador().ejecutar("hola"))


def test_flujo_completo_delegando_en_paralelo():
    def guion(mensajes, kwargs):
        sistema = mensajes[0]["content"]
        ultimo = mensajes[-1]
        if "coordinador" in sistema:
            if ultimo["role"] == "user":
                return respuesta(llamadas=[("delegar", {"tareas": [
                    {"agente": "programador", "tarea": "crea suma.py"},
                    {"agente": "tutor", "tarea": "explica qué es una suma"},
                ]})])
            assert "### programador" in ultimo["content"] and "### tutor" in ultimo["content"]
            return respuesta("El programador creó suma.py y el tutor explicó la suma.")
        if "programador senior" in sistema:
            if ultimo["role"] == "user":
                return respuesta(llamadas=[("escribir_archivo", {"ruta": "suma.py", "contenido": "print(1+1)"})])
            return respuesta("suma.py creado")
        return respuesta("Sumar es juntar cantidades")

    agent._clientes["ollama"] = ModeloFalso(guion)
    r = asyncio.run(crear_orquestador().ejecutar("crea suma.py y explícame la suma"))
    assert "suma.py" in r
    import tools
    assert tools.leer_archivo("suma.py") == "print(1+1)"


def test_error_de_un_agente_no_tumba_a_los_demas():
    def guion(mensajes, kwargs):
        if "tutor excelente" in mensajes[0]["content"]:
            raise RuntimeError("se cayó")
        if mensajes[-1]["role"] == "user":
            return respuesta(llamadas=[("listar_archivos", {})])
        return respuesta("revisión ok")

    agent._clientes["ollama"] = ModeloFalso(guion)
    r = asyncio.run(delegar([{"agente": "tutor", "tarea": "a"}, {"agente": "revisor", "tarea": "b"}]))
    assert "ERROR: RuntimeError" in r and "revisión ok" in r

"""Configura un entorno aislado para las pruebas (antes de importar el proyecto)."""
import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="granja-tests-"))
os.environ.update({
    "WORKSPACE": str(_tmp / "workspace"),
    "MEMORIA_DIR": str(_tmp / "memoria"),
    "LOGS_DIR": str(_tmp / "logs"),
    "CONFIRMAR_COMANDOS": "false",
    "PROVEEDOR_ORQUESTADOR": "ollama",
    "PROVEEDOR_AGENTES": "ollama",
    "MODELO_ORQUESTADOR": "fake",
    "MODELO_AGENTES": "fake",
    "MAX_PASOS": "6",
    "MAX_PARALELO": "2",
    "REINTENTOS": "2",
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    """Los reintentos no esperan de verdad en las pruebas."""
    import agent

    async def _nada(_):
        return None
    monkeypatch.setattr(agent.asyncio, "sleep", _nada)
    agent._clientes.clear()
    yield
    agent._clientes.clear()

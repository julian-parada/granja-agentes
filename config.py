"""Configuración general de la granja de agentes (se lee del archivo .env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).parent.resolve()
load_dotenv(RAIZ / ".env")

# ---------- Proveedores ----------
# anthropic usa su propio SDK; el resto usa el formato OpenAI (mismo código, distinta URL)
PROVEEDORES = {
    "anthropic":  {"base_url": None,                            "key_env": "ANTHROPIC_API_KEY",  "modelo": "claude-sonnet-5-5"},
    "ollama":     {"base_url": os.getenv("OLLAMA_URL", "http://localhost:11434/v1"), "key_env": None, "modelo": "qwen3.5:9b"},
    "deepseek":   {"base_url": "https://api.deepseek.com/v1",    "key_env": "DEEPSEEK_API_KEY",   "modelo": "deepseek-chat"},
    "groq":       {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",       "modelo": "openai/gpt-oss-120b"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",   "key_env": "OPENROUTER_API_KEY", "modelo": ""},  # elige uno en openrouter.ai/models?q=free
}

PROVEEDOR_ORQUESTADOR = os.getenv("PROVEEDOR_ORQUESTADOR", "groq")
PROVEEDOR_AGENTES = os.getenv("PROVEEDOR_AGENTES", "groq")

# Vacío = el modelo por defecto del proveedor
MODELO_ORQUESTADOR = os.getenv("MODELO_ORQUESTADOR", "")
MODELO_AGENTES = os.getenv("MODELO_AGENTES", "")

# ---------- Carpetas ----------
# Workspace: único lugar donde los agentes leen/escriben/ejecutan
WORKSPACE = Path(os.getenv("WORKSPACE", RAIZ / "workspace")).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)
# Memoria: notas que sobreviven entre sesiones
MEMORIA_DIR = Path(os.getenv("MEMORIA_DIR", RAIZ / "memoria")).resolve()
# Logs: registro de todo lo que hacen los agentes
LOGS_DIR = Path(os.getenv("LOGS_DIR", RAIZ / "logs")).resolve()

# ---------- Límites ----------
MAX_PASOS = int(os.getenv("MAX_PASOS", "25"))          # vueltas máximas por agente
MAX_PARALELO = int(os.getenv("MAX_PARALELO", "2"))     # agentes a la vez (1 si usas Ollama en un portátil)
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4000"))      # tokens máximos por respuesta
REINTENTOS = int(os.getenv("REINTENTOS", "4"))         # reintentos ante errores temporales (429, 5xx...)
MAX_HISTORIAL = int(os.getenv("MAX_HISTORIAL", "10"))  # turnos de conversación que recuerda el chat

# Si es true, te pregunta antes de ejecutar cada comando en la terminal
CONFIRMAR_COMANDOS = os.getenv("CONFIRMAR_COMANDOS", "true").lower() == "true"

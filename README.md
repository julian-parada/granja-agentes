# 🤖 Granja de Agentes

Un orquestador que recibe tu pedido, lo divide y lo reparte entre agentes especializados.
Funciona con **IA local gratis (Ollama)** o con APIs en la nube (Groq, DeepSeek, OpenRouter, Claude).

```
          Tú
          │
     Orquestador ──── divide y delega
     │   │   │   │   │
  prog test rev doc auto
          │
      workspace/   ← único lugar donde pueden leer, escribir y ejecutar
```

## 1. Instalación

```bash
cd granja-agentes
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env
```

## 2. Elegir proveedor

| Proveedor | Costo | Dónde sacar la key |
|---|---|---|
| `ollama` | Gratis, en tu PC | No necesita key |
| `groq` | Gratis con límite diario | console.groq.com |
| `openrouter` | Modelos gratis con límite | openrouter.ai |
| `deepseek` | Pago, muy barato | platform.deepseek.com |
| `anthropic` | Pago, el más capaz | console.anthropic.com |

Se configura en `.env` con `PROVEEDOR_ORQUESTADOR` y `PROVEEDOR_AGENTES`.
Cada agente también puede tener su propio proveedor en `agents.py`.

## 3. Ollama (IA local gratis)

1. Descarga e instala desde **ollama.com**.
2. Sube el contexto (por defecto es 4096 y se queda corto para agentes). En PowerShell:
   ```powershell
   setx OLLAMA_CONTEXT_LENGTH 16384
   ```
   Cierra Ollama desde la bandeja del sistema y vuelve a abrirlo.
3. Descarga un modelo:
   ```bash
   ollama pull qwen3.5:9b      # el mejor que aguanta tu PC (lento)
   ollama pull granite4:3b     # rápido, bueno llamando herramientas
   ```
4. En `.env`: `PROVEEDOR_AGENTES=ollama` y `MODELO_AGENTES=qwen3.5:9b` (o `granite4:3b`).

**Con 16 GB de RAM y sin GPU dedicada:** deja `MAX_PARALELO=1` y cierra el navegador mientras trabaja.

## 4. Combinación recomendada

```env
PROVEEDOR_ORQUESTADOR=groq     # piensa y divide rápido, gratis
GROQ_API_KEY=gsk_...
PROVEEDOR_AGENTES=ollama       # el trabajo pesado en local, ilimitado
MODELO_AGENTES=qwen3.5:9b
MAX_PARALELO=1
```

## 5. Uso

| Comando | Qué hace |
|---|---|
| `python main.py` | Modo chat con el orquestador |
| `python main.py "crea un script que organice mis descargas"` | Una orden directa |
| `python main.py --agente revisor "revisa todo el proyecto"` | Hablar con un solo agente |
| `python main.py --lista` | Ver agentes |

**Para trabajar sobre un proyecto tuyo:** cambia `WORKSPACE` en `.env` a la ruta del proyecto. Haz commit en Git antes, por si algo sale mal.

## 6. Agentes incluidos

| Agente | Rol | Ejecuta comandos |
|---|---|---|
| programador | Escribe y modifica código | ✅ |
| tester | Escribe y corre pruebas | ✅ |
| revisor | Busca bugs y fallas de seguridad | ❌ solo lee |
| documentador | README y documentación | ❌ |
| automatizador | Scripts para tareas repetitivas | ✅ |

## 7. Crear un agente nuevo

En `agents.py` agrega un bloque:

```python
"diseñador": {
    "descripcion": "Crea interfaces HTML/CSS bonitas y responsive.",
    "herramientas": ["leer_archivo", "escribir_archivo", "listar_archivos"],
    "proveedor": "groq",                     # opcional
    "modelo": "openai/gpt-oss-120b",     # opcional
    "prompt": "Eres diseñador frontend...",
},
```

El orquestador lo detecta solo.

## 8. Crear una herramienta nueva

En `tools.py`: escribe la función, regístrala en `HERRAMIENTAS` y agrégala a los agentes que la usen. Ideas: consultar MySQL, llamar tu API de Laravel, mandar mensajes por Telegram.

## 9. Seguridad

- Los agentes **no pueden salir** de la carpeta `WORKSPACE`.
- Comandos peligrosos (`rm -rf`, `format`, `shutdown`...) están bloqueados.
- Con `CONFIRMAR_COMANDOS=true` te pide permiso antes de cada comando.

## 10. Problemas comunes

| Síntoma | Solución |
|---|---|
| `Connection refused` con Ollama | Abre la app de Ollama o corre `ollama serve` |
| El agente repite lo mismo o no usa herramientas | Modelo muy pequeño: prueba `qwen3.5:9b` o pon el orquestador en Groq |
| Se olvida de lo que hacía | Sube `OLLAMA_CONTEXT_LENGTH` (paso 3) |
| Muy lento | Normal en CPU. Usa `granite4:3b` o Groq |
| `429 Too Many Requests` | Llegaste al límite gratis del proveedor; espera o cambia a Ollama |

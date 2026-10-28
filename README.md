# 🤖 Granja de Agentes

Un equipo de agentes de IA que programa, prueba, investiga en internet, busca artículos científicos reales,
enseña y redacta. Un **orquestador** conversa contigo y reparte el trabajo.

```
                     Tú
                     │
                Orquestador ── conversa, decide y delega
   ┌───────┬───────┬─┴──────┬─────────┬────────┬───────┐
programador tester revisor investigador tutor  asesor  redactor ...
   │                          │           │       │
workspace/              internet + OpenAlex   memoria/
```

## 1. Instalación

```bash
git clone https://github.com/julian-parada/granja-agentes
cd granja-agentes
py -m pip install -r requirements.txt
py -m pip install ddgs          # opcional: mejores búsquedas web
copy .env.example .env          # y pon tu key
```

Key gratis de Groq: **console.groq.com → API Keys**.

## 2. Uso

| Comando | Qué hace |
|---|---|
| `py main.py` | Chat con el orquestador (recuerda la conversación) |
| `py main.py "investiga X"` | Una sola orden |
| `py main.py --agente tutor` | Chat directo con un agente (ideal para estudiar) |
| `py main.py --agente asesor "temas de tesis sobre IA en educación"` | Orden directa a un agente |
| `py main.py --lista` | Ver agentes |

Dentro del chat: `/nuevo` (reinicia la conversación) · `/agentes` · `/memoria` · `/salir`

## 3. Agentes

| Agente | Para qué | Herramientas |
|---|---|---|
| **programador** | Escribe código y lo ejecuta para verificarlo | archivos, terminal |
| **tester** | Escribe y corre pruebas | archivos, terminal |
| **revisor** | Encuentra bugs y fallas de seguridad (solo lee) | leer archivos |
| **automatizador** | Scripts para tareas repetitivas | archivos, terminal |
| **documentador** | README y manuales | archivos |
| **investigador** | Investiga cualquier tema, contrasta fuentes y cita | web, artículos, memoria |
| **tutor** | Explica, adapta el nivel, hace quizzes y planes de estudio | web, memoria, archivos |
| **asesor** | Recomienda temas de investigación con artículos reales | artículos, web, memoria |
| **redactor** | Informes, ensayos y resúmenes con citas APA | archivos, web |

## 4. Ejemplos

```bash
# Investigación
py main.py "investiga el estado de la inteligencia artificial en la educación en Colombia y hazme un informe"

# Recomendaciones de investigación
py main.py --agente asesor "soy estudiante de ingeniería de sistemas, recomiéndame temas de tesis sobre ciberseguridad"

# Estudio (modo chat)
py main.py --agente tutor
Tú > explícame subnetting desde cero, voy para el examen de CCNA

# Programación con revisión
py main.py "crea una API en Python para tareas, con pruebas, y que el revisor la revise"
```

Los resultados quedan en `workspace/` (`investigaciones/`, `estudio/`, `documentos/`).

## 5. Herramientas

| Herramienta | Qué hace |
|---|---|
| `buscar_web` | Busca en internet (DuckDuckGo → respaldo Wikipedia). Soporta noticias |
| `leer_web` | Lee el texto de cualquier página |
| `buscar_articulos` | Artículos científicos **reales** (OpenAlex): autores, año, DOI, citas, resumen |
| `guardar_nota` / `buscar_notas` | Memoria permanente entre sesiones (`memoria/notas.json`) |
| `fecha_actual` | Para que sepa qué es "hoy" o "reciente" |
| `leer_archivo` / `escribir_archivo` / `listar_archivos` | Archivos dentro de `workspace/` |
| `ejecutar_comando` | Terminal dentro de `workspace/` (con confirmación) |

## 6. Robustez incluida

- **Reintentos automáticos** ante límites del plan gratis (429), servidor caído o tool calls mal formadas.
- **Anti-trampa**: si un agente responde sin usar herramientas, se le obliga a hacerlo de verdad.
- **Anti-invención**: todos los agentes tienen prohibido inventar datos, citas o referencias.
- **Contexto controlado**: recorta resultados viejos para no pasarse del límite del modelo.
- **Resumen parcial** si se acaban los pasos, en vez de quedarse sin respuesta.
- **Errores entendibles** (key inválida, modelo inexistente, sin conexión...).
- **Registro** de todo lo que hacen en `logs/AAAA-MM-DD.log`.

## 7. Proveedores

| Proveedor | Costo | Notas |
|---|---|---|
| `groq` ⭐ | Gratis con límite diario | Rápido; recomendado |
| `ollama` | Gratis, local | Lento en CPU; pon `MAX_PARALELO=1` |
| `openrouter` | Modelos gratis con límite | Elige modelo en openrouter.ai |
| `deepseek` | Pago, barato | |
| `anthropic` | Pago | El más capaz |

Cada agente puede tener su propio proveedor/modelo en `agents.py`.

## 8. Crear agentes y herramientas

**Agente nuevo** → agrega un bloque en `agents.py` (el orquestador lo detecta solo).
**Herramienta nueva** → función en `tools.py` + registro en `HERRAMIENTAS` + agrégala al agente.

## 9. Pruebas

```bash
py -m pip install pytest
py -m pytest -q
```

Usan un modelo simulado (no gastan API). También corren solas en GitHub (Actions) en cada push.

## 10. Seguridad

- Los agentes no pueden salir de `workspace/`.
- Comandos peligrosos bloqueados (`rm -rf`, `format`, `Remove-Item -Recurse`, `shutdown`...).
- `CONFIRMAR_COMANDOS=true` pide permiso antes de cada comando.
- `.env`, `memoria/` y `logs/` nunca se suben a GitHub.

## 11. Problemas comunes

| Síntoma | Solución |
|---|---|
| `API key inválida` | Revisa `GROQ_API_KEY` en `.env` |
| `El modelo no existe` | Deja `MODELO_*` vacío para usar el de por defecto |
| `Llegaste al límite` | Plan gratis agotado: espera o cambia de proveedor |
| Búsquedas web pobres | `py -m pip install ddgs` |
| `Connection refused` con Ollama | Abre Ollama o corre `ollama serve` |
| `python` abre la Microsoft Store | Usa `py` en vez de `python` |

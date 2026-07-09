# scrapy-pipeline · branch `prompt-only`

CLI para construir scrapers web usando un LLM. Le pasás una URL, un JSON Schema
del output esperado y casos de prueba; el pipeline pre-fetchea una página de
muestra, le pasa el HTML a un único agente que devuelve un scraper Python
completo, lo ejecuta contra los tests y reporta los diffs.

A diferencia de la rama `custom-agent`, esta variante **no usa tool calling**:
el modelo solo recibe texto y devuelve texto. Eso la hace compatible con
cualquier endpoint OpenAI-compatible, incluso si no soporta function calling
(LLMs locales como Qwen, LLaMA, etc.).

Soporta **Claude (Anthropic)** y cualquier **endpoint OpenAI-compatible**.

## Pipeline

```
URL + schema + tests
        │
        ▼
┌───────────────────┐
│ Pre-fetch (Pwt.)  │  → runs/<ts>/sample.html
└─────────┬─────────┘
          ▼
┌───────────────────┐  prompt: URL + schema + tests + sample HTML
│ Discovery Agent   │  ←─── feedback en retry
│ (single shot LLM) │  → runs/<ts>/agent_response.md
└─────────┬─────────┘  → scrapers/<slug>.py  (extraído del bloque ```python```)
          ▼
┌───────────────────┐
│ Run tests         │  subprocess por caso
│ (determinista)    │  → runs/<ts>/results.json
└─────────┬─────────┘
          ▼
┌───────────────────┐  jsonschema.validate + diff recursivo
│ Evaluate          │  → runs/<ts>/report.md
│ (determinista)    │     "VERDICT: PASS|FAIL (k/n passing)"
└─────────┬─────────┘
          ▼
    ¿VERDICT: PASS?
    sí → fin
    no → vuelve a Discovery con el report como feedback
         (hasta --max-retries)
```

## Instalación

```powershell
pip install -e .
playwright install chromium
cp .env.example .env
# editar .env con tu backend (ver Configuración del LLM)
```

Requiere Python 3.10+.

## Configuración del LLM

### Opción A — Claude (Anthropic)

```env
ANTHROPIC_API_KEY=sk-ant-...
```

### Opción B — Endpoint OpenAI-compatible (LLM local/on-premise)

```env
CUSTOM_LLM_BASE_URL=https://tu-servidor/v1
CUSTOM_LLM_API_KEY=tu-token   # omitir si no requiere auth
```

Compatible con Qwen, LLaMA, Mistral, vLLM, Ollama, LM Studio, LiteLLM, etc.
Esta rama **no requiere** que el endpoint soporte function calling.

## Uso

```powershell
scrapy-pipeline run `
  --url https://books.toscrape.com `
  --schema examples/books_toscrape/schema.json `
  --tests examples/books_toscrape/tests.json
```

| Flag | Env | Default | Descripción |
|------|-----|---------|-------------|
| `--url` | — | — | URL inicial (también de donde se pre-fetchea HTML si no hay tests) |
| `--schema` | — | — | JSON Schema del output esperado |
| `--tests` | — | — | JSON `[{name, url, expected}]` (el primer `url` es el sample) |
| `--model` | — | `sonnet` | `sonnet` \| `opus` \| `haiku` \| `local` o un model id |
| `--max-retries` | — | `2` | Reintentos con feedback si falla la evaluación |
| `--slug` | — | (auto) | Nombre del archivo en `scrapers/` |
| `--show-browser` | — | off | Playwright con ventana visible (debug) |
| `--custom-api-url` | `CUSTOM_LLM_BASE_URL` | — | URL base del endpoint OpenAI-compatible |
| `--custom-api-key` | `CUSTOM_LLM_API_KEY` | — | Bearer token del endpoint custom |

Exit codes: `0` PASS, `2` aborto (HTML no fetchable o respuesta sin código), `3` FAIL.

### Inspeccionar una corrida previa

```powershell
scrapy-pipeline inspect runs/<dir> --artifact report
```

`--artifact`: `scraper`, `results`, `report`, `sample_html`, `agent_response`, `manifest`.

## Estructura de cada corrida

```
runs/20260525-143012-books_toscrape/
├── input_schema.json   # copia del schema usado
├── input_tests.json    # copia de los tests
├── sample.html         # HTML pre-fetcheado que vio el agente
├── agent_response.md   # respuesta cruda del LLM
├── results.json        # outputs reales del scraper por test
├── report.md           # reporte determinista (VERDICT + diffs)
└── manifest.json       # paths para `inspect`
```

El scraper generado vive en `scrapers/<slug>.py` y es runnable standalone:

```powershell
python scrapers/books_toscrape.py https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html
```

## Diseño (qué cambió respecto a `custom-agent`)

- **Un único agente** (`Discovery`). No hay DOM Mapping, Implementation, Test
  Runner ni Evaluation agents separados. El LLM hace todo el trabajo en una
  sola llamada.
- **Sin tool calling**: el modelo recibe el HTML pre-fetcheado dentro del
  prompt y emite el scraper como texto en un bloque ```` ```python ```` que el
  orquestador extrae y persiste.
- **Evaluación 100% determinista**: `jsonschema.validate` + diff recursivo en
  Python. No hay LLM en la evaluación, así que el verdict es reproducible y
  barato.
- **Feedback loop**: si la evaluación falla, el `report.md` completo se pasa
  como `feedback` al agente en la siguiente iteración (hasta `--max-retries`).

## Troubleshooting

**"No LLM configured"** — configurá `ANTHROPIC_API_KEY` o
`CUSTOM_LLM_BASE_URL` en `.env`, o pasá `--custom-api-url` por flag.

**"Agent response did not contain a python code block"** — el modelo emitió
prosa sin bloque ```` ```python ````. Pasa con modelos chicos; probá con
`--model opus` o un modelo más capaz en el endpoint custom. El response crudo
queda en `runs/<dir>/agent_response.md`.

**El modelo emite `<think>...</think>`** (Qwen3, DeepSeek-R1, etc.) — el
pipeline los stripea automáticamente antes de extraer el código.

**El scraper hace timeout** — subí `DEFAULT_TIMEOUT` en `scrapy_cli/tools/exec.py`.

## Limitaciones

- El agente solo ve UN sample HTML (el de la primera URL de tests). Si los
  tests apuntan a páginas estructuralmente distintas, podría fallar.
- No maneja login flows, CAPTCHAs ni proxies rotatorios.
- Modelos chicos pueden no producir Python ejecutable en una sola pasada; los
  retries con feedback ayudan pero no son mágicos.

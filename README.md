# scrapy-pipeline

CLI multi-agente para construir scrapers web usando Claude. Le pasás una URL, un
JSON Schema del output esperado y casos de prueba, y un pipeline de 5 agentes
descubre el sitio, mapea selectores, genera un scraper Python, lo ejecuta y
evalúa los resultados.

## Pipeline

```
URL + schema + tests
      │
      ▼
┌─────────────────┐   Discovery Agent      → runs/<ts>/plan.md
│ 1. Discovery    │   (Claude + Playwright)
└────────┬────────┘
         ▼
┌─────────────────┐   DOM Mapping Agent    → runs/<ts>/dom_map.json
│ 2. DOM Mapping  │   (Claude + Playwright)
└────────┬────────┘
         ▼
┌─────────────────┐   Implementation Agent → scrapers/<slug>.py
│ 3. Implementation│  (Claude + filesystem)
└────────┬────────┘
         ▼
┌─────────────────┐   Test Runner          → runs/<ts>/results.json
│ 4. Test Runner  │   (subprocess por test)
└────────┬────────┘
         ▼
┌─────────────────┐   Evaluation Agent     → runs/<ts>/report.md
│ 5. Evaluation   │   (Claude + jsonschema + diff)
└────────┬────────┘
         ▼
   ¿VERDICT: PASS?
   sí → fin
   no → vuelve a Implementation con el report como feedback
        (hasta --max-retries)
```

## Instalación

```powershell
# 1. Clonar e instalar deps
pip install -e .

# 2. Instalar el navegador de Playwright (solo la primera vez)
playwright install chromium

# 3. Configurar API key
cp .env.example .env
# editar .env y poner tu ANTHROPIC_API_KEY
```

Requiere Python 3.10+.

## Uso

```powershell
scrapy-pipeline run `
  --url https://books.toscrape.com `
  --schema examples/books_toscrape/schema.json `
  --tests examples/books_toscrape/tests.json
```

Opciones:

| Flag | Default | Descripción |
|------|---------|-------------|
| `--url` | — | URL inicial que ve Discovery |
| `--schema` | — | JSON Schema del output esperado |
| `--tests` | — | JSON con `[{name, url, expected}]` |
| `--model` | `sonnet` | `sonnet` \| `opus` \| `haiku` o un model id completo |
| `--max-retries` | `2` | Reintentos de Implementation si Evaluation falla |
| `--slug` | (auto del host) | Nombre del archivo en `scrapers/` |
| `--show-browser` | off | Ejecuta Playwright con ventana visible (debug) |

Exit codes: `0` PASS, `2` aborto (ej. DOM map inválido), `3` FAIL.

### Inspeccionar una corrida previa

```powershell
scrapy-pipeline inspect runs/20260525-143012-books_toscrape --artifact report
```

`--artifact` admite: `plan`, `dom_map`, `scraper`, `results`, `report`, `manifest`.

## Formato del schema

Un JSON Schema estándar (Draft 2020-12). El Implementation Agent usa los nombres
y tipos de las `properties` para decidir conversiones; la Evaluation Agent corre
`jsonschema.validate` contra cada output del scraper.

Ver [`examples/books_toscrape/schema.json`](examples/books_toscrape/schema.json).

## Formato de los tests

Array de objetos, cada uno con:

```json
{
  "name": "id-corto-del-caso",
  "url": "URL específica que el scraper recibe",
  "expected": { ... output esperado ... }
}
```

`expected` es opcional — sin él, Evaluation solo valida el schema (no compara
valores).

Ver [`examples/books_toscrape/tests.json`](examples/books_toscrape/tests.json).

## Estructura de cada corrida

```
runs/20260525-143012-books_toscrape/
├── input_schema.json     # copia del schema usado
├── input_tests.json      # copia de los tests
├── plan.md               # output del Discovery Agent
├── dom_map.json          # output del DOM Mapping Agent
├── results.json          # outputs reales del scraper por test
├── report.md             # reporte de Evaluation (VERDICT: PASS/FAIL ...)
└── manifest.json         # resumen + paths para `inspect`
```

El scraper generado vive en `scrapers/<slug>.py` y es runnable standalone:

```powershell
python scrapers/books_toscrape.py https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html
```

## Diseño

- **Tools por agente**:
  - Discovery, DOM Mapping → solo browser (Playwright)
  - Implementation → solo `read_file` / `write_file` (sandboxed a `scrapers/` y `runs/`)
  - Test Runner → determinista (subprocess) — corre cada test sin LLM
  - Evaluation → solo `read_file` + diff y jsonschema computados en Python
- **Prompt caching** activado en `system` y `tools` (Anthropic SDK).
- **Feedback loop**: Evaluation emite `VERDICT: PASS` / `VERDICT: FAIL` en su
  primera línea. Si falla, el report completo se pasa como `feedback` al
  Implementation Agent en la próxima iteración.
- **Sandbox**: el filesystem tool solo permite leer/escribir bajo
  `scrapers/` y `runs/<ts>/`. Los agentes no pueden tocar otros archivos del repo.

## Troubleshooting

**"ANTHROPIC_API_KEY is not set"** — copiá `.env.example` a `.env` y poné tu key,
o exportala como variable de entorno.

**"Executable doesn't exist at .../chromium..."** — corré `playwright install
chromium` una vez.

**El DOM Mapping devuelve JSON inválido** — pasa a veces si el modelo envuelve la
respuesta en markdown. El parser intenta extraer el primer bloque `{...}`. Si
falla repetidamente, probá `--model opus`.

**El scraper hace timeout** — subí el timeout del subprocess editando
`DEFAULT_TIMEOUT` en `scrapy_cli/tools/exec.py`, o reducí los casos de prueba.

## Limitaciones

- No maneja login flows, CAPTCHAs ni proxies rotatorios.
- Pensado para sitios con páginas de detalle individuales (un URL → un objeto).
  Para crawlear listings paginados completos hace falta un agente extra.
- Los test cases del ejemplo asumen valores estables de [books.toscrape.com](
  https://books.toscrape.com), que es un sandbox público diseñado para esto.

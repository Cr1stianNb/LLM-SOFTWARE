# llmscrape

A spec-guided web-scraping CLI built as a **five-stage pipeline**. Given a URL,
an expected-output schema and a small set of test cases, it extracts the
requested fields and verifies them against the test cases.

```
Discovery → DOM Mapping → Implementation → Test Runner → Evaluation
  (LLM)        (LLM)          (LLM)        (deterministic)   (LLM)
```

Four stages reason with an LLM (through a single OpenAI-compatible client); only
the **Test Runner** is deterministic.

---

## Install (from a clean clone)

Requires Python 3.9+.

```bash
git clone <this-repo> && cd LLM-SOFTWARE
python -m pip install -r requirements.txt   # requests, beautifulsoup4
python -m pip install -e .                  # installs the `llmscrape` command
```

You can run it either as `llmscrape …` or as `python -m llmscrape …`.

## Run the bundled example (no model required)

The repository ships a frozen HTML snapshot, an example schema, one test case,
and a recorded LLM **cassette** so the example runs fully offline:

```bash
python -m llmscrape run `
  --schema  fixtures/example_schema.json `
  --tests   fixtures/example_tests.json `
  --llm-mode replay --cassette fixtures/example_cassette.json `
  --pretty -v
```

This prints the extracted result and an evaluation report, and exits `0`
because the single test case passes (non-zero if any case fails). Add `-v` to
see every stage's intermediate output on stderr.

## Configure the LLM (live mode)

All four LLM stages talk **OpenAI Chat Completions** through one client. Point it
at any OpenAI-compatible endpoint (local vLLM / Ollama / LM Studio, or a remote
provider). Configure via environment variables — the API key is **only** read
from the environment, never hardcoded:

```bash
export LLM_BASE_URL="http://localhost:8000/v1"   # default
export LLM_API_KEY="sk-..."                       # omit for keyless local servers
export LLM_MODEL="qwen3-32b"                       # default; configured model
```

**Model:** `qwen3-32b` (Qwen3, open-weight, servable locally). Other valid ids:
`qwen3-14b`, `qwen3-8b`, `qwen3-30b-a3b`, or remote `qwen3-coder-plus`. Override
per-run with `--model`. The same values can be passed as flags
(`--base-url`, `--api-key`, `--model`) instead of env vars.

## Scrape a live site

```bash
llmscrape scrape "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html" `
  --schema fixtures/example_schema.json --pretty
```

`scrape` fetches the **live** URL, builds the extraction program via the LLM
stages, applies it, and prints the structured result. Use `--html FILE` to run
against a local HTML file instead of the network.

## Help

```bash
llmscrape --help
llmscrape run --help
llmscrape scrape --help
```

## Run the tests

```bash
python -m unittest discover -s tests
```

---

## Inputs & outputs

**Inputs** (all documented in `--help`):

1. **URL** — the target page (`scrape` command), or the fixtures referenced by
   the test cases (`run` command).
2. **Output schema** — JSON describing each field and its type
   (`string` / `number` / `integer` / `boolean`). See
   [fixtures/example_schema.json](fixtures/example_schema.json).
3. **Test cases** — small (input → expected) pairs. See
   [fixtures/example_tests.json](fixtures/example_tests.json).

**Outputs:** a structured JSON result conforming to the schema, plus an
evaluation report (per-case pass/fail and an aggregate verdict). Exit code is
`0` when all cases pass, non-zero otherwise.

## Live site vs. frozen snapshot

- **Live extraction** (`scrape`) hits the real URL — the normal use case.
- **Test evaluation** (`run`) executes against **frozen snapshots** in
  `fixtures/`, never the network, so results are reproducible regardless of site
  changes, downtime, or rate-limiting. The HTML-fetch layer
  ([llmscrape/fetch.py](llmscrape/fetch.py)) can point at the network or a local
  fixture without changing the rest of the pipeline.

## Key design decisions

- **The Implementation stage emits a *declarative* extraction program** (a set
  of field rules: selector + extract mode + regex/value-map/transforms) rather
  than executable code. A small deterministic engine
  ([llmscrape/extract.py](llmscrape/extract.py)) applies it. This keeps the Test
  Runner deterministic and safe.
- **The pass/fail verdict is deterministic**, computed by exact type-aware
  comparison in the Test Runner — *not* by the Evaluation LLM, which only writes
  the human-readable narrative. The verdict never depends on LLM variability.
- **One LLM client** ([llmscrape/llm/client.py](llmscrape/llm/client.py)) shared
  by all four reasoning stages, with `live` / `replay` / `record` modes. Replay
  reads a cassette keyed by stage, which is how the example runs with no model.
- **Controlled errors**: unreachable URL, missing field, mismatched test case,
  or an LLM endpoint that is down all produce a clean message and a specific
  exit code, never an uncaught stack trace
  ([llmscrape/core/errors.py](llmscrape/core/errors.py)).

## Layout

```
llmscrape/
  cli.py                 entry point, argument parsing, --help
  config.py              LLM config from env/flags
  fetch.py               HTML acquisition: live network or local fixture
  extract.py             deterministic extraction engine
  core/types.py          first-class shared types (schema, program, test case…)
  core/errors.py         controlled errors + exit codes
  llm/client.py          single OpenAI-compatible client (live/replay/record)
  pipeline/
    discovery.py         stage 1 (LLM)
    dom_mapping.py       stage 2 (LLM)
    implementation.py    stage 3 (LLM)
    test_runner.py       stage 4 (deterministic)
    evaluation.py        stage 5 (LLM)
    runner.py            orchestrator
fixtures/                frozen HTML snapshot + example schema/tests/cassette
tests/                   deterministic-core unit tests
```

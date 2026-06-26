# CLAUDE.md — Guía del proyecto (condición de harness: h1-context)

> Este archivo **solo existe en la rama `h1-context`** (y, más adelante, en `h4-full`). Es la
> manipulación experimental de la función *context ingress* del control plane. En `h0-default` este
> archivo no está presente. No debe contener obligaciones de verificación ni de recuperación: esas
> son otras funciones (h2, h3) y mezclarlas confundiría las variables.
>
> Lo que este archivo aporta es **contexto de arquitectura, convenciones y comandos** que el prompt
> de tarea (`TASK.md`) deliberadamente no da.

## Qué es este proyecto

Una CLI de web scraping guiado por especificación, organizada como un pipeline de cinco etapas:
Discovery → DOM Mapping → Implementation → Test Runner → Evaluation. Cuatro etapas razonan con un
LLM; solo el Test Runner es determinista. Ver `TASK.md` para la especificación funcional completa.

## Arquitectura propuesta

Organiza el código de modo que cada etapa del pipeline sea un módulo independiente con una interfaz
clara de entrada/salida. Una estructura recomendada:

```
.
├── cli/                  # punto de entrada, parsing de argumentos, --help
├── pipeline/
│   ├── discovery.*       # etapa 1 (LLM): propone estrategia de extracción
│   ├── dom_mapping.*     # etapa 2 (LLM): selectores y nodos DOM por campo
│   ├── implementation.*  # etapa 3 (LLM): construye la lógica de extracción
│   ├── test_runner.*     # etapa 4 (determinista): ejecuta los casos de prueba
│   └── evaluation.*      # etapa 5 (LLM): compara real vs esperado, veredicto
├── llm/                  # cliente LLM único, OpenAI-compatible (ver abajo)
├── core/                 # tipos compartidos: esquema de output, caso de prueba, resultado
├── fixtures/             # snapshot congelado del HTML real + caso de prueba de ejemplo
└── README                # instalación y ejecución desde cero
```

Cada etapa recibe un objeto de contexto del pipeline y devuelve una versión enriquecida del mismo,
de forma que el resultado intermedio de cada etapa sea inspeccionable.

## Acceso al LLM: un único cliente OpenAI-compatible

Todas las etapas con LLM (Discovery, DOM Mapping, Implementation, Evaluation) deben llamar al modelo
**a través de un único cliente** en `llm/`, que habla el esquema **OpenAI Chat Completions**. No
disperses llamadas al LLM por todo el código: una sola interfaz, reutilizada por las cuatro etapas.

- El cliente se configura con tres parámetros, leídos de configuración/entorno, nunca hardcodeados:
  - `base_url` — endpoint OpenAI-compatible (local: vLLM/Ollama/LM Studio; o proveedor remoto).
  - `api_key` — leída de variable de entorno; nunca en el código ni en el repo.
  - `model` — identificador del modelo Qwen3 a usar.
- **Modelo:** Qwen3, variante OpenAI-compatible. Fija un único ID y mantenlo constante.
  Valor por defecto sugerido: `qwen3-32b` (open-weight, servible local con vLLM/Ollama).
  Alternativas válidas: `qwen3-14b`, `qwen3-8b`, `qwen3-30b-a3b`, o vía proveedor remoto
  `qwen3-coder-plus`. Documenta en el README cuál quedó configurado.
- El Test Runner (etapa 4) **no** toca el cliente LLM: es determinista por diseño.

## Convenciones

- **Esquema de output como tipo de primera clase.** Define el esquema esperado como una estructura
  tipada compartida en `core/`, no como diccionarios sueltos.
- **Observabilidad por etapa.** Un flag de verbosidad (`-v` / `--verbose`) debe mostrar el resultado
  intermedio de cada etapa. Esto es parte del criterio de calidad de `TASK.md`.
- **Errores controlados.** URL inalcanzable, campo ausente en el HTML, caso de prueba que no
  coincide, o endpoint del LLM caído son condiciones esperadas: manéjalas con mensajes claros y
  códigos de salida, nunca con un stack trace sin capturar.
- **Determinismo de la evaluación de prueba.** Aunque la etapa Evaluation use LLM para el reporte
  legible, el veredicto pass/fail de cada caso debe poder reproducirse de forma estable; no dejes que
  el veredicto dependa de la variabilidad del LLM cuando la comparación campo a campo sea exacta.
- **Configuración por archivo o argumento, documentada en `--help`.**

## Manejo del sitio: vivo vs. snapshot

- El modo normal de la CLI extrae del **sitio en vivo** (la URL que recibe).
- Los **casos de prueba** corren contra el **snapshot congelado** en `fixtures/`, no contra la red.
  Esto mantiene la evaluación reproducible. Mantén esa separación clara en el código: la capa de
  obtención de HTML debe poder apuntar a la red o a un fixture local sin cambiar el resto del
  pipeline.

## Comandos de build y ejecución

> Completa esta sección con los comandos reales una vez elijas el lenguaje y las dependencias.
> Mantenla actualizada: es la referencia que se usará para verificar el criterio de "terminado".

- Instalación: `…`
- Configuración del LLM (variables de entorno): `…`
- Ejecución sobre el caso de ejemplo: `…`
- Ejecución sobre un sitio en vivo: `…`
- Ayuda: `<cli> --help`

## Fuera de alcance de este archivo

No incluyas aquí reglas sobre obligación de escribir tests, loops de self-review, archivos de
progreso ni protocolos de recuperación. Esas funciones del control plane pertenecen a otras ramas
del experimento y deben mantenerse separadas para no confundir las variables.

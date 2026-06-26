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
Discovery → DOM Mapping → Implementation → Test Runner → Evaluation. Ver `TASK.md` para la
especificación funcional completa.

## Arquitectura propuesta

Organiza el código de modo que cada etapa del pipeline sea un módulo independiente con una interfaz
clara de entrada/salida. Una estructura recomendada:

```
.
├── cli/                  # punto de entrada, parsing de argumentos, --help
├── pipeline/
│   ├── discovery.*       # etapa 1: propone estrategia de extracción
│   ├── dom_mapping.*     # etapa 2: selectores y nodos DOM por campo
│   ├── implementation.*  # etapa 3: construye la lógica de extracción
│   ├── test_runner.*     # etapa 4: ejecuta los casos de prueba
│   └── evaluation.*      # etapa 5: compara real vs esperado, veredicto
├── core/                 # tipos compartidos: esquema de output, caso de prueba, resultado
├── fixtures/             # snapshot congelado del HTML real + caso de prueba de ejemplo
└── README                # instalación y ejecución desde cero
```

Cada etapa recibe un objeto de contexto del pipeline y devuelve una versión enriquecida del mismo,
de forma que el resultado intermedio de cada etapa sea inspeccionable.

## Convenciones

- **Separación LLM/determinista explícita.** Las etapas que llaman a un LLM deben aislar esa llamada
  detrás de una interfaz única, de modo que el resto del pipeline sea determinista y testeable sin
  red. No esparzas llamadas a LLM por todo el código.
- **Esquema de output como tipo de primera clase.** Define el esquema esperado como una estructura
  tipada compartida en `core/`, no como diccionarios sueltos.
- **Observabilidad por etapa.** Un flag de verbosidad (`-v` / `--verbose`) debe mostrar el resultado
  intermedio de cada etapa. Esto es parte del criterio de calidad de `TASK.md`.
- **Errores controlados.** URL inalcanzable, campo ausente en el HTML, o caso de prueba que no
  coincide son condiciones esperadas: manéjalas con mensajes claros y códigos de salida, nunca con
  un stack trace sin capturar.
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
- Ejecución sobre el caso de ejemplo: `…`
- Ejecución sobre un sitio en vivo: `…`
- Ayuda: `<cli> --help`

## Fuera de alcance de este archivo

No incluyas aquí reglas sobre obligación de escribir tests, loops de self-review, archivos de
progreso ni protocolos de recuperación. Esas funciones del control plane pertenecen a otras ramas
del experimento y deben mantenerse separadas para no confundir las variables.

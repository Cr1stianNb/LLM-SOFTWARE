# TASK.md — Especificación de la tarea

> Este archivo es **idéntico en todas las ramas** del experimento (h0–h4). Describe *qué* construir,
> no *cómo*. Las decisiones de arquitectura interna, estructura de carpetas y convenciones
> corresponden al harness de cada rama (p. ej. al `CLAUDE.md` en la rama h1-context).

## Objetivo

Construir una herramienta de línea de comandos (CLI) para *web scraping* guiado por una
especificación. Dada la URL de un sitio, una definición del output esperado y un conjunto acotado
de casos de prueba, la herramienta debe extraer la información solicitada y verificar su corrección
contra los casos de prueba.

La CLI organiza el trabajo como un **pipeline de cinco etapas** (descritas abajo). Algunas etapas
razonan con un modelo de lenguaje (LLM) y otras son deterministas. La elección concreta de qué
etapa usa LLM y cuál no se deja al implementador, dentro de las restricciones de esta especificación.

El lenguaje de implementación lo decide el implementador.

## Entradas

La CLI recibe tres entradas:

1. **URL del sitio oficial** — la página objetivo de la cual extraer información.
2. **Definición del output esperado** — un esquema que describe los campos a extraer y su tipo
   (por ejemplo, en JSON Schema o equivalente). Define la forma del resultado.
3. **Casos de prueba acotados** — un conjunto pequeño de pares (entrada → output esperado) que
   permiten verificar que la extracción es correcta.

Las tres entradas se pasan a la CLI mediante argumentos o archivos de configuración; el formato
exacto lo decide el implementador, pero debe estar documentado en el `--help` de la CLI.

## Salida

- El **resultado extraído**, conforme al esquema de output esperado, emitido en un formato
  estructurado (JSON por defecto).
- Un **reporte de evaluación** que indica, por cada caso de prueba, si el output real coincide con
  el esperado, y un veredicto agregado (todos pasan / cuántos fallan).
- Códigos de salida apropiados (0 si todos los casos pasan; distinto de 0 si alguno falla).

## El pipeline de cinco etapas

El procesamiento se organiza como un pipeline. Cada etapa recibe el resultado de la anterior.

1. **Discovery** — Analiza el sitio y propone cómo obtener la información (qué páginas, qué
   estrategia de extracción). Esta etapa puede razonar con un LLM.
2. **DOM Mapping** — Identifica selectores, estructura HTML y nodos del DOM relevantes para cada
   campo del esquema. Puede combinar heurísticas deterministas con razonamiento de LLM.
3. **Implementation** — Genera/configura la lógica concreta de extracción a partir del mapeo de la
   etapa anterior.
4. **Test Runner** — Ejecuta los casos de prueba definidos contra la extracción.
5. **Evaluation** — Compara el output real contra el output esperado, campo por campo, y produce el
   reporte de evaluación y el veredicto.

El implementador decide la frontera exacta entre etapas con LLM y etapas deterministas, pero el
pipeline debe ser observable: debe poder verse el resultado intermedio de cada etapa (por ejemplo,
con un flag de verbosidad o logs por etapa).

## Estrategia de prueba (sitio real, snapshot congelado)

Los casos de prueba se ejecutan contra un **snapshot congelado** del HTML de un sitio real, incluido
en el repositorio como *fixture*. Esto hace los resultados reproducibles: todas las ejecuciones ven
exactamente el mismo HTML.

- La extracción contra el **sitio en vivo** debe estar soportada como modo de operación normal de la
  CLI (es el caso de uso real).
- La **evaluación de los casos de prueba** corre contra el snapshot local, no contra la red, para que
  el resultado no dependa de cambios del sitio, caídas o rate-limiting.
- El repositorio incluye el fixture y un caso de prueba de ejemplo completo y funcional.

## Requisitos de calidad

- La CLI expone una ayuda clara (`--help`) que documenta entradas, salidas y flags.
- El proyecto incluye instrucciones de instalación y de ejecución que funcionan desde cero.
- El pipeline maneja con gracia los errores previsibles: URL inalcanzable, HTML que no contiene un
  campo esperado, caso de prueba que no coincide. Ninguno de estos debe producir un fallo no
  controlado (stack trace sin manejar).
- El código está organizado de forma que cada etapa del pipeline sea identificable y testeable por
  separado.

## Criterio de "terminado"

El proyecto se considera terminado cuando, partiendo de un clon limpio del repositorio y siguiendo
únicamente las instrucciones de instalación incluidas, es posible ejecutar la CLI sobre el caso de
prueba de ejemplo y obtener un reporte de evaluación con veredicto.

> Nota de evaluación (no para el implementador): el éxito verificado (VTS) se mide con una suite de
> tests independiente y oculta que **no** forma parte de este repositorio y que el implementador no
> ve durante la construcción.

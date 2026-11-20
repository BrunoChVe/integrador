# 0022 — El informe de limpieza y el diccionario los genera el pipeline

- **Estado:** aceptada
- **Fecha:** 2026-10-17
- **Afecta a:** `etapa_3_preparacion/dvc.yaml` (etapa `documentar`, antes `documentar`), `etapa_3_preparacion/codigo/documentar.py`,
  `etapa_3_preparacion/codigo/seleccionar.py`, `etapa_3_preparacion/codigo/bloques.py`,
  `etapa_3_preparacion/params.yaml: informe`, `params.yaml: select.perfil`
- **Origen:** al revisar la preparación de datos contra lo que CRISP-DM pide al
  final de la etapa 3 faltaban dos salidas documentales: el informe de limpieza
  y la descripción del conjunto resultante, campo por campo. Al revisar también
  aparecieron tres defectos que impedían reproducir o trazar.
- **Continúa a:** [0020](0020-tres-etapas-y-sin-borrador.md)

## Decisión

**1. La etapa `documentar` genera las dos salidas.** Lee
`reportes/raw_profile.json`, `reportes/bloques.json` y los bloques, y escribe:

| salida | qué es |
|---|---|
| `reportes/informe_limpieza.json` | métrica: cada hallazgo de calidad de `seleccionar`, la decisión, dónde vive y la evidencia medida sobre los bloques |
| `reportes/informe_limpieza.md` | lo mismo, legible y con el texto que lo interpreta |
| `docs/diccionario/diccionario.csv` y `.md` | cada campo del punto `.laz` y cada columna de `bloque_index.csv`, con tipo, origen y rango medido |

**2. La cobertura se comprueba en cada ejecución.** La etapa termina con error
si `seleccionar` emite un hallazgo sin respuesta, o si el esquema real de los bloques
tiene un campo sin descripción. «El diccionario cubre el 100 % de las columnas»
deja de ser una promesa y se convierte en una comprobación.

**3. `seleccionar` diagnostica y `documentar` responde.** Cada hallazgo llevaba un campo
`handled_by` que nombraba la etapa que lo resolvía. Cuando 0020 borró esas etapas,
el campo siguió diciendo `stage 06_weak_labels` o `stage 04_ground` sin que nada
fallara. Ahora la respuesta vive en un solo sitio, junto a la evidencia que la
comprueba.

## Por qué una etapa aparte y no dentro de `bloques`

`bloques` tarda ~2,75 h sobre los 5 443 M puntos. `documentar` tarda segundos.
Corregir una frase del informe no puede obligar a recortar 49 GB. Se consideró
meterlo en `bloques` para no añadir etapas (0020 insiste en mantenerlas pocas) y
se descartó por eso.

## Las cinco tareas de la etapa 3, y dónde está cada una

El pipeline no tiene una etapa por tarea, y no es un descuido:

| tarea | dónde | por qué así |
|---|---|---|
| 3.1 seleccionar | `seleccionar` + `select.*` | todas las nubes `.laz` entran; la fotogrametría queda fuera (0009); `keep_dimensions` fija las columnas |
| 3.2 limpiar | `documentar` | **no se elimina ningún punto por ser ruido.** El filtro estadístico de atípicos se probó y destruía los cables (0004); los activos son objetos delgados, justo lo que un filtro de ruido quita. Lo que sí se corrige (CRS, color) se corrige al escribir el bloque, y `documentar` lo documenta y lo mide |
| 3.3 construir | — | los rasgos geométricos se construían para el borrador que se borró en 0020. Se construirán dentro del entrenamiento, por tesela, cuando se elija la red: dependen de ella |
| 3.4 integrar | — | hay una sola fuente: la nube LiDAR. La trayectoria (`LadybugEvents_*.txt`) está versionada, pero ningún paso la necesita aún. La única unión real será la de la etiqueta con el punto, que hace `etapa_3_preparacion/herramientas/registrar_anotacion.py` por coordenada |
| 3.5 dar formato | `bloques` | rejilla de 200 m anclada a UTM, LAS 1.4 con CRS (0018) |

## Defectos corregidos de paso

- **`reportes/bloques.json` llevaba `elapsed_s`**, el tiempo de ejecución. Cada ejecución
  daba una huella distinta, así que repetir la etapa con los mismos datos,
  código y parámetros cambiaba el `dvc.lock`. La prueba de reproducibilidad
  (rehacer forzando y comprobar que el lock no cambia) no podía pasar nunca.
  El tiempo se sigue imprimiendo, pero ya no se guarda en el archivo.
- **Constantes de muestreo dentro de `s01_catalog.py`** (`SAMPLE_FILES`,
  `SAMPLE_CHUNK`, un `200_000` literal). Pasan a `select.perfil`.
- **El hallazgo Q3 no podía dispararse.** Exigía un 100 % de puntos con un solo
  retorno, y el perfil mide ~95 %. Mientras tanto, `params.yaml` decía que
  `number_of_returns` era «constant 1». Ahora el hallazgo reporta la fracción
  medida y el comentario dice la verdad.
- **Q1 solo aparecía si *ningún* archivo declaraba CRS.** Una entrega mezclada,
  que es el peor caso, pasaba sin aviso. Ahora basta con un archivo sin CRS.

## Qué queda sin resolver

- La evidencia de los rangos se mide sobre `informe.bloques_muestra` bloques, no
  sobre los 799. El CRS sí se comprueba en todos, porque solo exige leer la
  cabecera.
- El informe cubre los hallazgos que `seleccionar` sabe detectar. Un problema que
  nadie programó como hallazgo no aparece. Cuando se descubra uno, se añade a
  `quality_findings`, y la guarda de cobertura obliga a responderlo.

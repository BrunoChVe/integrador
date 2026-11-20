<!-- Generado por etapa_3_preparacion/codigo/documentar.py (etapa `documentar` de dvc.yaml). No editar a mano: se sobrescribe en cada `dvc repro`. -->

# Informe de limpieza

Responde, hallazgo por hallazgo, a los problemas de calidad que la etapa `seleccionar` encontró en el crudo (`reportes/raw_profile.json`). Para cada uno dice qué se hizo, dónde vive la decisión y qué se **midió** sobre los bloques para comprobar que funcionó. La versión de máquina es `reportes/informe_limpieza.json`. Por qué no hay más limpieza que esta: [ADR 0022](../../docs/decisiones/0022-informe-de-limpieza-y-diccionario-generados.md).

## Del crudo al bloque

| | puntos |
|---|---:|
| crudo (cabeceras de los .laz) | 5 443 246 642 |
| núcleo en 799 bloques | 5 443 203 444 |
| descartados | 43 198 (0.000794 %) |

Los descartados son bloques con menos de tiling.min_points = 2000 puntos no se escriben: roces de la trayectoria en el borde de un escaneo. No se elimina ningún punto por ser ruido o atípico; el bloque se guarda a resolución completa.

## Hallazgos

### Q1 · `header.crs` · high

**Hallazgo.** 474 of 474 files declare no CRS (parse_crs() returns None), while coordinates are UTM 18S valued.

**Decisión: corregido.** Cada bloque se escribe con el CRS de `project.crs_epsg` (EPSG:32718, WGS 84 / UTM 18S) estampado en la cabecera (`io_cloud.write_las`). Las coordenadas no se transforman: ya estaban en UTM 18S, solo faltaba declararlo.

**Dónde:** `etapa_3_preparacion/params.yaml: project.crs_epsg`, `codigo/common/io_cloud.py: write_las`

**Evidencia medida** (cumple): `{"bloques_con_crs_correcto": 799, "bloques": 799}`

**Queda sin resolver.** Ninguno si la evidencia da 100 %. Depende de pyproj: sin el, write_las escribe la geometria sin CRS y esta comprobacion lo detecta.

### Q2 · `classification` · blocking

**Hallazgo.** Every sampled point carries classification == 1. The delivered set is 100% unlabelled.

**Decisión: pendiente (camino critico).** No se puede limpiar: falta la etiqueta. Se anota a mano, sobre el bloque de 200 m a resolucion completa y sin preetiqueta. La verdad de campo se guarda aparte, en `annotation_revisada/` versionada con DVC, porque `bloques` borra su carpeta al regenerarse.

**Dónde:** `docs/decisiones/0023-solo-postes-con-su-luminaria.md`, `docs/decisiones/0018-el-bloque-de-anotacion-sustituye-a-la-tesela.md`, `docs/decisiones/0020-tres-etapas-y-sin-borrador.md`, `herramientas/registrar_anotacion.py`

**Evidencia medida** (cumple): `{"classification_min": 0.0, "classification_max": 0.0}`

**Queda sin resolver.** Sin etiquetas no hay entrenamiento supervisado. Los bloques salen con classification = 0 (sin clasificar) y la etiqueta se une al punto al registrar la anotacion.

### Q3 · `number_of_returns` · medium

**Hallazgo.** 94.6% of sampled points are single-return; the rest have 2-3 returns.

**Decisión: aceptado.** `number_of_returns` y `return_number` se descartan (`select.keep_dimensions`). El retorno multiple es marginal y no permite la regla de primer/ultimo retorno para separar suelo de cable; cuando haga falta altura sobre el suelo se calculara por geometria.

**Dónde:** `etapa_3_preparacion/params.yaml: select.keep_dimensions`, `etapa_3_preparacion/params.yaml: select.umbral_retorno_unico`

**Evidencia medida** (cumple): `{"number_of_returns_max": 0.0}`

**Queda sin resolver.** Se pierde la informacion de retorno del ~5 % de puntos que la tienen. Se acepta.

### Q4 · `red/green/blue` · low

**Hallazgo.** Colour is stored in 16-bit LAS fields but only uses the 0-255 range.

**Decisión: corregido.** El color llega en campos LAS de 16 bits con valores de 0-255. Se lee como 8 bits y se escribe desplazado 8 bits, que es la convencion LAS: asi CloudCompare y cualquier normalizacion por 65535 ven el color real y no una nube casi negra.

**Dónde:** `codigo/common/io_cloud.py: _extract, write_las`

**Evidencia medida** (cumple): `{"rgb_max": 65280.0, "rgb_multiplo_de_256": true}`

**Queda sin resolver.** Ninguno: el desplazamiento es exacto y reversible.

### Q5 · `density` · medium

**Hallazgo.** Density varies 5-3844 pts/m2 between files (mobile mapping: near the trajectory is dense, far is sparse).

**Decisión: aceptado y diferido al entrenamiento.** No se iguala la densidad aqui. El bloque se guarda a resolucion completa porque es lo que se abre para anotar, y un poste lejano de la trayectoria ya tiene pocos puntos. La igualacion (reduccion por voxel) se hara al cortar la tesela de entrenamiento, sin tocar el bloque.

**Dónde:** `docs/decisiones/0018-el-bloque-de-anotacion-sustituye-a-la-tesela.md`, `etapa_3_preparacion/params.yaml: tiling.tesela_m`

**Evidencia medida** (cumple): `{"densidad_bloque_pts_m2": {"min": 0.0, "p50": 105.3, "max": 1701.2}}`

**Queda sin resolver.** Cualquier rasgo de radio fijo calculado sobre el bloque crudo se comporta distinto cerca y lejos de la trayectoria.

## Controles

| control | resultado |
|---|---|
| `point_source_id_no_nulo` | cumple |
| `gps_time_no_nulo` | cumple |
| `dimensiones_conservadas_presentes` | cumple |

Medidos sobre los bloques de muestra: `b_1493_43239.laz`, `b_1483_43252.laz`, `b_1490_43269.laz`, `b_1483_43294.laz`, `b_1468_43339.laz`.

# 0004 — El SOR de manual borra los conductores; usar un filtro con guarda

- **Estado:** aceptada
- **Fecha:** 2026-09-06
- **Afecta a:** `params.yaml: clean.*`, `src/common/geometry.py`,
  `src/stages/s04_clean.py`
- **Sustituye a:** el «aplicar un filtro estadístico de ruido (SOR) y un
  downsampling por rejilla de vóxeles» del planteamiento inicial

## Decisión

**No** se aplica Statistical Outlier Removal de forma global. El ruido se
elimina con un filtro de tamaño de componente conexa, y el SOR solo se ejecuta
donde la vecindad local **no** es lineal.

## Por qué la receta estándar es incorrecta aquí

El SOR marca un punto cuando su distancia media a sus `k` vecinos más cercanos
supera `media + std_ratio * sigma` sobre la nube. Léelo como la descripción de un
objeto físico:

> un punto que está lejos de todo lo demás, en una zona dispersa y aislada de la
> nube

Eso es un **conductor de 1-2 cm suspendido a 8 m de altura**, muestreado unas
pocas veces por metro, con nada más que aire alrededor. Y también es, con las
mismas palabras, un retorno espurio por multicamino o un pájaro. El SOR no puede
distinguirlos, porque a escala de `k = 16` vecinos son idénticos.

La consecuencia es concreta y grave: las clases **6 (power_line)** y
**7 (telecom_line)** son la razón de ser del proyecto, y ejecutar SOR antes de la
segmentación elimina parte de ellas. Peor: las elimina **en silencio** y
**preferentemente en los extremos dispersos de un vano**, que es justo donde se
toma una medida de distancia de seguridad.

El mismo argumento se aplica, menos gravemente, a la clase 5 (poste) en su parte
superior.

## Qué se hace en su lugar

Tres filtros, del más discriminante al menos:

**1. Recorte en altura (`clean.z_clip`)** — expresado en altura *sobre el
suelo*, no en Z absoluta. Por eso la etapa 03 (suelo) va antes que la 04
(limpieza): los umbrales no existen hasta que existe la superficie del terreno.
Elimina retornos bajo suelo y ruido de cielo sin tocar nada estructural.

**2. Filtro de tamaño de componente conexa (`clean.cluster_filter`)** — la
herramienta principal. Se construye el grafo de vecindad ε con `eps_m = 0.40` y
se descartan las componentes menores de `min_cluster_points = 24`.

Funciona **precisamente por** la propiedad que derrota al SOR. Un cable es
disperso pero **conexo**: un vano de 10 m a esta densidad es una única componente
de más de mil puntos, y sobrevive por muy aislado que esté del resto de la
escena. Un retorno por multicamino es una componente de uno o dos puntos y no
sobrevive. El filtro se apoya en la topología, no en la densidad local, así que
es ciego a lo que hace fallar al SOR.

**3. SOR con guarda (`clean.guarded_sor`)** — se conserva, porque sí atrapa ruido
de rango real que forma pequeños grumos densos, pero condicionado:

```python
raw     = raw_sor_mask(xyz, k, std_ratio)              # lo que el SOR quiere borrar
flagged = raw & (linearity < linearity_exemption)      # lo que se le permite borrar
```

Cualquier punto cuya linealidad local al radio de cable (0.30 m) supere **0.85**
queda exento. Los cables y las aristas de poste son lineales; el ruido de rango y
el multicamino no.

La etapa reporta `sor_points_saved_by_guard` por tesela — el recuento de puntos
que el SOR de manual habría borrado y la guarda rescató. Ese número, en
`reports/cleaning.json`, es la evidencia continua de esta decisión. Si alguna vez
se acerca a cero, hay que revisar este registro.

## Evidencia medida

En prueba controlada con un conductor muestreado de forma realista:

| | Puntos borrados | De ellos, cable |
|---|---|---|
| SOR de manual | 210 | **90 de 90 — el 100 % del conductor** |
| SOR con guarda | 126 | 6 |

Sobre los datos reales, a lo largo de las 36 teselas de la fase 1, la guarda
rescató **78 448 puntos tipo cable**.

Un matiz honesto sobre esa cifra: mide puntos que el SOR marcaría y que la guarda
exime por linealidad > 0.85. No todos son necesariamente conductores reales —una
arista de poste también es lineal—, pero el sentido del error importa: eximir de
más conserva datos, eximir de menos destruye la clase objetivo.

## La segunda desviación: reducir no es sobrescribir

El filtro de rejilla de vóxeles del planteamiento se aplica a
`downsample.model_m = 0.05`, pero los puntos a resolución completa **se
conservan**, junto con `voxel_inverse` — el mapa de cada punto original a su
vóxel.

Dos razones:

- **5 cm, no 10 ni 20.** Un conductor mide 1-2 cm de sección. A 5 cm sobrevive
  como una cadena de un vóxel de ancho. A 10 cm, dos hilos de telecom adyacentes
  se funden en un solo grumo y las clases 6 y 7 dejan de ser separables — la
  reducción destruiría la etiqueta antes de que la red llegara a verla.
- **La medición se hace sobre geometría cruda.** El entregable es una distancia
  de seguridad. Medirla sobre centroides de vóxel incorpora un error de
  cuantización de 5 cm al número. En su lugar, la red predice sobre la nube
  reducida y las etiquetas vuelven por `voxel_inverse` — una consulta de índice
  exacta, sin búsqueda de vecino más cercano y sin interpolación.

Para la reducción se usa el promedio de centroide (no «quedarse con el primer
punto»), porque promediar los ~4 puntos de un vóxel atenúa parte del error
aleatorio de rango de ~3 cm del sensor.

## Consecuencias

- La etapa 04 calcula linealidad a un radio, duplicando un poco de la etapa 05.
  Se acepta: la alternativa es dejar que el SOR corra a ciegas sobre los
  conductores.
- Los **objetos móviles** (vehículos estacionados y en marcha, peatones) **no**
  se eliminan. Forman agrupaciones grandes y coherentes que pasan todos los
  filtros de aquí. Quedan registrados como asunto abierto en
  `reports/cleaning.json` y el anotador los marcará como `unclassified`.
  Eliminarlos bien requiere diferenciación multipasada, que una entrega de una
  sola pasada no soporta.

## Cómo comprobar que la decisión sigue siendo correcta

```bash
python src/viewer/view_tile.py --stage clean --color linearity
```

Los conductores deben aparecer como líneas continuas brillantes. Si un vano
muestra huecos que no son oclusión, la guarda está demasiado estricta: hay que
subir `clean.guarded_sor.linearity_exemption` o desactivar el SOR por completo y
confiar solo en el filtro de componentes.

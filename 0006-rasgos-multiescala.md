# 0006 — Tres radios de vecindad, y sin normalizar a propósito

- **Estado:** aceptada
- **Fecha:** 2026-09-06
- **Afecta a:** `params.yaml: features.*`, `src/common/geometry.py`

## Decisión

Los descriptores de PCA local se calculan a **tres radios — 0.30, 0.80 y
2.00 m** — y **no se normalizan** en la etapa de rasgos.

## Por qué tres radios

Un solo radio no puede describir a la vez un conductor y una fachada:

| Radio | Qué resuelve |
|---|---|
| 0.30 m | Escala de cable. Un conductor es lineal aquí y casi nada más lo es. |
| 0.80 m | Escala de poste. Un poste es vertical y lineal; una fachada aún no es plana. |
| 2.00 m | Escala de fachada. Un muro es plano aquí; un cable *sigue* siendo lineal. |

El hallazgo Q5 afila el argumento: la densidad medida varía entre **44 y 1152
pts/m²** entre archivos, porque la cartografía móvil muestrea densamente cerca de
la trayectoria y de forma dispersa lejos de ella. Un radio fijo ve, por tanto, un
número de vecinos radicalmente distinto según la tesela. La pila multiescala es
lo que mantiene el descriptor comparable a lo largo de todo el levantamiento.

## Un número que sorprenderá a quien ajuste esto

Sobre un **plano perfectamente plano**, la `planarity` mide aproximadamente
**0.66**, no 1.0.

No es un error. La implementación vectorizada se contrastó contra una referencia
ingenua e independiente sobre cinco formas sintéticas; diferencia máxima 3e-8, es
decir, idénticas dentro de la precisión de float32. La causa es el sesgo de
muestreo finito: con k = 64 vecinos colocados al azar, el mayor autovalor de la
covarianza muestral es sistemáticamente mayor que el segundo, así que
`(e2-e3)/e1 < 1` incluso para un plano ideal. Los puntos interiores miden ~0.71;
los del borde, que ven medio disco, ~0.62.

Por eso los umbrales de `params.yaml` están en 0.35-0.60 y no cerca de 1.0.
**Quien los reajuste debería medir primero el valor alcanzable sobre una
superficie conocida** en lugar de asumir el ideal de libro — poner
`min_planarity: 0.9` no coincidiría con nada, en silencio.

## Por qué la normalización NO ocurre aquí

Ajustar un escalador sobre todas las teselas antes de partir train/val es
exactamente la fuga de información documentada en la literatura (Kapoor y
Narayanan 2023, *Patterns*). El escalador se ajusta en la etapa 07 sobre la
**partición de entrenamiento, solo puntos de núcleo**, y se escribe en
`data/processed/normalisation.json` con una nota que lo deja registrado.

## Nota de implementación, porque costó una reescritura

`eigen_features` es álgebra de arrays por lotes, no un bucle sobre puntos.

La implementación obvia —`query_ball_point` y luego un bucle llamando a
`np.linalg.eigh` sobre cada covarianza 3×3— se midió en **23 000 puntos/s** y
convertía la limpieza en la etapa más lenta del pipeline por un margen amplio. La
versión por lotes lanza una consulta de k fijo al árbol KD por lote, construye
las covarianzas con un solo `matmul`, y llama a `eigh` una vez sobre un array
apilado `(lote, 3, 3)`, que NumPy recorre en C.

`matmul` y no `einsum`: producen covarianzas idénticas bit a bit, pero `matmul`
despacha a un gemm por lotes de BLAS mientras `einsum` cae a su propio bucle —
0.04 s frente a 0.44 s por lote de 150 000.

La k fija con `distance_upper_bound=radius` no es idéntica a una consulta por
radio verdadera: un punto con más de `max_neighbours` vecinos dentro del radio
conserva solo los k más cercanos. Es el mismo truncamiento que aplicaba la
versión con bucle, y es lo que acota el coste en zonas de suelo densas.

En la misma línea, **todo el trabajo de vecindad de la etapa 04 se ejecuta sobre
la nube de vóxeles de 5 cm**, no a resolución completa. Una bola de 0.30 m en
datos crudos de cartografía móvil contiene cientos de puntos, y `query_pairs`
sobre una tesela completa se acerca a mil millones de pares. Las decisiones de
filtrado se toman a resolución de vóxel —que es la resolución a la que el ruido y
la estructura realmente difieren aquí— y se propagan a resolución completa a
través del índice de vóxeles.

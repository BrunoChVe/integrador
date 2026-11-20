# 0008 — El umbral de confianza borraba tres clases en silencio

- **Estado:** aceptada (defecto encontrado y corregido)
- **Fecha:** 2026-09-06
- **Afecta a:** `params.yaml: weak_labels.min_confidence`,
  `src/stages/s07_dataset.py`

## Qué pasó

`weak_labels.min_confidence` estaba en **0.6**. Las confianzas por regla que
asigna la etapa 06 son:

| Regla | Confianza |
|---|---|
| power_line | 0.75 |
| telecom_line | 0.65 |
| pole | 0.60 |
| building | 0.55 |
| road | 0.50 |
| sidewalk | 0.40 |

La etapa de dataset descarta los puntos por debajo del umbral *antes* de calcular
la distribución de clases y los pesos. Con el umbral en 0.6, **pista, vereda y
construcción quedaron eliminadas del conjunto de entrenamiento por completo** —
el 58 % de los puntos del borrador, y todas las clases de suelo.

La primera ejecución imprimió exactamente esto:

```
train class distribution (confidence-filtered):
  pole                  294,051   87.08%
  telecom_line           32,545    9.64%
  power_line             11,064    3.28%
```

Tres clases, donde la ontología tiene ocho. Nada dio error. La tabla Parquet se
escribió, el diccionario de datos se generó, las 47 columnas quedaron
documentadas y todo el conjunto parecía sano. Un modelo entrenado sobre esa tabla
habría sido estructuralmente incapaz de reconocer una pista.

## Por qué era fácil que pasara desapercibido

Los dos parámetros están en bloques distintos de `params.yaml` y se eligieron por
razones distintas: las confianzas por regla expresan la confianza *relativa* en
cada regla geométrica, mientras que el umbral se fijó como un genérico «descarta
los dudosos». Ninguno está mal por separado. Lo que está mal es la interacción.

Es el modo de fallo que más cuesta ver: un pipeline puede ser perfectamente
reproducible y aun así producir una tabla incorrecta. El archivo de anotación habría registrado fielmente que
`min_confidence: 0.6` produjo esta salida, y reproducirlo habría reproducido el
defecto con exactitud.

## La corrección

Dos cambios: uno al valor y otro para que no pueda volver a esconderse.

**1. Umbral bajado a 0.35**, por debajo de la menor confianza de regla, con la
restricción escrita al lado del valor en `params.yaml`:

> Debe estar POR DEBAJO de la menor confianza por regla, o clases enteras
> desaparecen del entrenamiento en silencio.

**2. La etapa de dataset ahora reporta ambas distribuciones** — todos los puntos
del borrador y los que superan el umbral — en paralelo, e imprime un aviso
explícito nombrando cualquier clase que el umbral haya eliminado:

```
train class distribution (all drafted | above confidence floor 0.35):
  unclassified   3,998,618 (38.38%) |          0 ( 0.00%)
  road           3,051,095 (29.29%) |  3,051,095 (47.52%)
  building       2,328,124 (22.35%) |  2,328,124 (36.26%)
  sidewalk         703,065 ( 6.75%) |    703,065 (10.95%)
  pole             294,051 ( 2.82%) |    294,051 ( 4.58%)
  telecom_line      32,545 ( 0.31%) |     32,545 ( 0.51%)
  power_line        11,064 ( 0.11%) |     11,064 ( 0.17%)
```

`classes_lost_to_confidence_floor` se escribe además en `reports/dataset.json`,
así que la condición es comprobable por máquina y no solo visible para quien lea
la consola.

## El mejor uso de la confianza

Filtrar es el instrumento romo. `label_confidence` viaja con cada fila de la
tabla de modelado y el uso previsto es como **peso por punto en la función de
pérdida**: un punto de vereda incierto debería contribuir menos que un conductor
seguro, no nada en absoluto. El umbral entonces solo necesita excluir los puntos
que ninguna regla reclamó.

## Qué dice esto del balance de clases

Con todas las clases presentes, el desbalance es descarnado y conviene decirlo
sin rodeos:

**pista supera a power_line 276 : 1.**

Por eso `dataset.class_balance` es `inverse_sqrt_frequency`, por eso la pérdida
incluye un término Lovász (optimiza IoU directamente en lugar de exactitud) y por
eso existe `model.metrics.report_classes: [6, 7]`. Una IoU media sobre ocho
clases estaría dominada por pista y construcción —las fáciles y numerosas—
mientras que las dos clases que de verdad le importan al negocio suman menos del
0.7 % de los puntos.

## Actualización · 2026-09-11

Las cifras de arriba son las del momento de la decisión. Al añadir `green_area`
([0010](0010-clase-area-verde.md)), su regla va antes del reparto pista/vereda y
se queda con 37 250 puntos de entrenamiento. Pista baja a 3 042 101 y el
desbalance pasa a **275 : 1**. La decisión no cambia: la confianza de la regla
nueva (0.45) supera el umbral (0.35), y `classes_lost_to_confidence_floor` sigue
vacío. Las cifras vigentes están en `reports/dataset.json`.

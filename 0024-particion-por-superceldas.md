# 0024 — Partir por superceldas espaciales, no por escaneo

- **Estado:** aceptada
- **Fecha:** 2026-10-17
- **Afecta a:** `etapa_3_preparacion/dvc.yaml` (etapa `particionar`),
  `etapa_3_preparacion/codigo/particionar.py`,
  `etapa_3_preparacion/params.yaml: particion`
- **Sustituye a:** [0007](0007-particion-y-fugas.md), en la unidad de
  partición. Sus reglas sobre normalización, pesos de clase y anillo siguen
  vigentes.

## Contexto

0007 partía por **escaneo** cuando solo había tres escaneos de ate y no se
tocaban. Hoy hay dieciséis, en dos distritos, y **las pasadas del vehículo se
solapan**: el mismo id de bloque (el mismo suelo y los mismos postes) aparece en
varios escaneos. En ate pasa con 24 de 106 ids. Si se parte por escaneo, ese
poste entra en train desde una pasada y en test desde otra. El modelo lo
reconocería por su geometría exacta y la métrica mediría memoria, no
generalización. Ninguna comprobación lo detecta: el número simplemente sale
mejor de lo que es.

## Decisión

**La unidad de partición es el suelo.** Los bloques de 200 m se agrupan en
**superceldas de `particion.supercelda_m` = 1 000 m** sobre la misma rejilla
UTM absoluta. Cada supercelda va **entera** a una partición, junto con todos los
escaneos que la cubren.

- El orden de las superceldas se baraja con `project.random_seed` y se asignan
  una a una a la partición que más lejos esté de su proporción objetivo
  (`particion.proporciones`: 70 / 15 / 15), medida en **puntos de núcleo** y no
  en número de bloques.
- La etapa falla si un mismo id de bloque queda en dos particiones.
- Cuenta los pares de bloques vecinos que caen en particiones distintas. Solo
  comparten el anillo de contexto de `tiling.buffer_m`, que según 0007 queda
  fuera de la pérdida y de toda métrica.

## Por qué 1 km

Una supercelda tiene que ser lo bastante grande para que el borde, donde un
poste de test podría compartir contexto con uno de train, sea una fracción
pequeña de su área. Con 1 km, el anillo de 10 m alrededor ocupa un ~4 % del
área. También tiene que ser lo bastante pequeña para que haya varias por
partición: con los dos distritos salen 57. Una supercelda más grande dejaría
test en una o dos piezas y la métrica dependería de qué calles tocaron.

## Por qué test ya no está vacío

0007 dejaba test vacío por dos motivos: tres escaneos eran muy pocos y las
etiquetas eran un borrador. Ninguno de los dos se sostiene. Hay dos distritos y
dieciséis escaneos, y desde 0020 se anota a mano, sin borrador.

## Qué queda sin resolver

- La partición se hace sobre **bloques**, no sobre bloques anotados. Hoy la
  verdad de campo es poca (~30 postes BT en un bloque), así que una partición
  puede quedarse sin ejemplos de una clase. Cuando se escriba el entrenamiento,
  hay que cruzar `datos/final/particion.csv` con la anotación y reportar
  cuántos postes caen en cada partición antes de entrenar.
- Asignar por puntos no garantiza que cada partición tenga los dos distritos.
  En la corrida actual los tres los tienen, pero no es una regla: si deja de
  pasar, habrá que estratificar por distrito.

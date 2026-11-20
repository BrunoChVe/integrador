# 0007 — Partir por escaneo, antes de calcular ningún estadístico

- **Estado:** reemplazada en la unidad de partición por [0024](0024-particion-por-superceldas.md); las reglas de normalización, pesos de clase y anillo siguen vigentes
- **Fecha:** 2026-09-06
- **Afecta a:** `params.yaml: dataset.*`, `src/stages/s07_dataset.py`

## Decisión

- Unidad de partición: **tesela**, agrupada por **escaneo**.
- `train: [AVP01MT2611202501, AVP01MT2611202503]`,
  `val: [AVP01MT2611202502]`, `test: []`.
- Las constantes de normalización y los pesos de clase se ajustan sobre la
  **partición de entrenamiento, solo puntos de núcleo**, y en ningún otro sitio.

## Por qué no una partición aleatoria por punto

Los puntos vecinos comparten vecindad. Una partición aleatoria por punto pone *el
mismo conductor* —a veces, literalmente, vóxeles contiguos de él— en
entrenamiento y en validación. El modelo reporta entonces una IoU que refleja
memorización de geometría local, no generalización.

Es la forma más común en que los resultados de segmentación de nubes de puntos
salen mal en silencio, y es invisible en la métrica: el número se ve excelente.

Partir por **escaneo** es más estricto que partir por tesela: escaneos distintos
son calles distintas, iluminación distinta, geometría de trayectoria distinta. Es
el sustituto más cercano disponible de «un distrito que el modelo nunca ha
visto».

## Por qué `test` está deliberadamente vacío

Con tres escaneos, reservar uno para test deja uno para entrenar y uno para
validar — demasiado poco de cada cosa como para significar algo.

Y de forma más decisiva: un conjunto de test evaluado contra etiquetas
**borrador** (ver 0005) no mide exactitud, mide acuerdo con las reglas de
etiquetado débil. Un modelo que reprodujera las reglas a la perfección sacaría
1.0 y no valdría nada.

`test` permanece vacío hasta que llegue un segundo `Grupo` o exista un conjunto
de teselas corregidas por una persona. Queda registrado en lugar de omitirse en
silencio, porque una partición de test vacía es una limitación real sobre cada
número que este proyecto reporte, y pertenece al informe y no a una nota al pie.

## Puntos de buffer

Cada tesela lleva un anillo de contexto de 5 m para que los rasgos de vecindad no
se calculen con vecindades truncadas en los bordes. Esos puntos aparecen en dos
teselas.

`is_core` los marca. **Los puntos de buffer deben excluirse de la función de
pérdida y de toda métrica.** Incluirlos cuenta dos veces los mismos puntos e
infla el resultado. La columna está documentada en el diccionario de datos, y el
ejemplo de lectura que hay allí la filtra.

## Lista de control de fugas para este pipeline

- [x] la partición se declara en `params.yaml` antes de que corra la etapa de dataset
- [x] la normalización se ajusta solo sobre train/núcleo, y el artefacto lo dice
- [x] los pesos de clase se ajustan solo sobre train
- [x] agrupado por escaneo, así que ninguna estructura física cruza la partición
- [x] los puntos de buffer están marcados y excluidos por convención documentada
- [ ] partición de test — aplazada, ver arriba

El pipeline hace visible el orden; no detecta la fuga. Declarar el orden como
dependencias obliga a dejarlo por escrito, pero alguien tiene que mirarlo
igualmente. Para eso está esta lista.

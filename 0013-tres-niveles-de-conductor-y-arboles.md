# 0013 — Once clases: MT separada de BT, y los árboles salen de «sin clasificar»

- **Estado:** aceptada (los umbrales de altura son **provisionales**)
- **Fecha:** 2026-09-14
- **Afecta a:** `params.yaml: ontology` (v3), `params.yaml: weak_labels.wires`,
  `params.yaml: weak_labels.tree`, `src/stages/s06_weak_labels.py`
- **Supersede parcialmente a:** [0010](0010-clase-area-verde.md), que dejaba la
  vegetación en altura dentro de `unclassified`

## Decisión

La ontología pasa de nueve a **once clases**:

| id | Cambio |
|---|---|
| 6 | `power_line` → **`conductor_lv`** (`conductor_bt`). Ya no agrupa BT y MT |
| 8 | `jardin_area_verde` → **`area_verde`**: el término generaliza mejor |
| 9 | **`conductor_mv`** (`conductor_mt`), nueva |
| 10 | **`tree`** (`arbol`), nueva |

Los ids 0 a 8 se conservan. Las clases nuevas se añaden al final, como manda
[0010](0010-clase-area-verde.md): renumerar rompería cualquier tesela anotada y
cualquier checkpoint entrenado.

## Por qué separar MT de BT

Son **decisiones de negocio distintas**. Las distancias de seguridad, los
criterios de intervención y el riesgo asociado no son los mismos para media que
para baja tensión, así que un entregable que las mezcle obliga al proyectista a
volver a separarlas a mano — justo el trabajo que el proyecto quiere eliminar.

## Por qué separar el árbol del área verde

También son problemas distintos. **El área verde es contexto de superficie**:
dice dónde termina la calzada y empieza el jardín. **La copa importa por su
proximidad a los conductores**, que es una medición de despeje. Mezclarlas
obligaría a separarlas después por altura, que es exactamente lo que la clase
debería resolver.

Como efecto secundario, `unclassified` deja de contener vegetación en altura y
vuelve a ser lo que debe ser: ruido y aquello sobre lo que el anotador duda.

## Por qué NO se separa el sardinel

Se evaluó y se descartó. Un sardinel mide **12 a 20 cm** de alto. Con vóxeles de
5 cm son tres o cuatro vóxeles de espesor: la clase tendría poquísimos puntos,
su regla sería ruidosa y el anotador tendría que corregirla casi siempre. Sigue
dentro de `sidewalk`, que es donde el sardinel ya se declaraba como la línea de
quiebre vectorizable entre pista y vereda.

## Los umbrales, y de dónde salen

Del conocimiento de campo del equipo sobre el distrito:

> Los postes de baja llegan **hasta 8 m**; los de media están **sobre los 11 m**.
> La media se nota porque va acerada y lleva casi siempre sus **tres fases**;
> cuando el armado es autoportante se ve como una sola línea, pero **siempre más
> alta** que la baja.

De ahí los tres niveles sobre altura del suelo:

```yaml
weak_labels:
  wires:
    telecom_max_hag_m: 6.5     # por debajo, telecomunicaciones (clase 7)
    lv_min_hag_m: 6.5          # 6.5-9.0 m -> baja tensión (clase 6)
    mv_min_hag_m: 9.0          # por encima, media tensión (clase 9)
```

Se reclaman **de arriba hacia abajo**, y cada regla toma lo que la anterior dejó
libre. Así un punto no puede ser MT y BT a la vez.

## Las tres fases: una firma específica de la media tensión

El conocimiento de campo del equipo añade el dato que vuelve fiable la regla:

> La red de **BT es predominantemente autoportante**: las tres fases van
> trenzadas sobre un mensajero de acero, así que en el escaneo aparece como
> **una sola línea**. La **MT** en cambio lleva casi siempre **sus tres fases**
> separadas, sobre cruceta o apiladas verticalmente en el poste.

De ahí que el detector de tres fases sea un discriminador **específico de MT**:
un trío de vanos paralelos no puede ser BT por construcción. Lo contrario no se
cumple —una línea sola puede ser BT, o una MT también autoportante— y para ese
caso solo queda la altura. Por eso los niveles siguen existiendo y por eso **la
BT se reclama sobre todo por altura**: es la firma esperada, no una carencia.

El detector agrupa vanos que sean paralelos (coseno ≥ 0.98), separados entre
**0.3 y 1.5 m medidos como distancia perpendicular entre ejes en 3D** —lo que
cubre el armado horizontal y el vertical con la misma condición— y situados
lado a lado, no uno detrás del otro. Un grupo conexo de tres o más vanos por
encima del nivel de BT es media tensión, con confianza 0.7.

**El piso de altura del haz no es decorativo.** Sin él, la regla agrupaba tres
cables de telefonía paralelos —que es literalmente lo que son las telarañas— y
los declaraba media tensión: 5 668 puntos mal etiquetados en la primera versión.

Medido sobre las 36 teselas: **el 60 % de los puntos de MT se identifica por el
armado** y el 40 % restante por altura. Además, la regla movió 1 907 puntos de
BT a MT: vanos de media tensión que cuelgan por debajo de los 9 m y que el
umbral clasificaba mal.

**Los umbrales siguen siendo una convención**, y gobiernan el 40 % de la MT que
el armado no alcanza a identificar, además de toda la frontera entre BT y
telecomunicaciones. El riesgo queda declarado: si están mal, el error es
sistemático y afecta a las dos clases que justifican el proyecto. La diferencia
frente a la primera versión es que ahora **la mayor parte de la MT se sostiene
en geometría medible**, no en un número elegido.

**La validación pendiente** es contrastar contra postes reales del distrito, y
sigue siendo la primera tarea de anotación.

## La regla del árbol

```yaml
  tree:
    min_hag_m: 2.0
    hue_deg: [70, 170]
    min_saturation: 0.12
    min_value: 0.12
    min_sphericity: 0.22       # al radio de 0.80 m
    confidence: 0.5
```

La esfericidad es lo que la separa de una fachada verde: **una copa es
volumétrica, una pared es plana**. Medido sobre seis teselas densas, el 0.97 %
de los puntos tiene verde saturado por encima de 2 m.

## Debilidades conocidas

- **Una rama delgada a más de 4 m es lineal**, así que la regla de conductores
  la reclama antes de que la del árbol llegue a verla. El orden es deliberado
  —los cables son la clase crítica— pero produce falsos conductores en calles
  arboladas. Es lo primero que verá el anotador.
- **La media tensión autoportante** se ve como una sola línea, igual que la
  baja: solo la altura las separa, y es justo el supuesto sin validar.
- **El árbol hereda la debilidad del color** de [0010](0010-clase-area-verde.md):
  el follaje seco o en sombra se escapa de la banda de tono.

## Qué hubo que tocar, y qué no

Solo `params.yaml` y `s06_weak_labels.py`, que es donde se asignan las clases.
**Ni `config.py`, ni `io_cloud.py`, ni `geometry.py`, ni las etapas 00 a 05, ni
el visor, ni el verificador de calidad**: todos leen la ontología desde
`params.yaml` y ninguno sabe cuántas clases hay. Esa es la razón por la que la
ontología vive en parámetros y no en el código.

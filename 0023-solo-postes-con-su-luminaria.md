# 0023 — Solo postes, con la luminaria como parte del poste

- **Estado:** aceptada
- **Fecha:** 2026-10-17
- **Afecta a:** `params.yaml: ontology` (v7), `etapa_3_preparacion/herramientas/registrar_anotacion.py`,
  `README.md`
- **Origen:** decisión del equipo al cerrar el alcance de esta fase del
  capstone. Se detectan **postes de BT y de MT**; cada uno puede tener luminaria
  o no tenerla, pero la luminaria no es una clase.
- **Sustituye en parte a:** [0017](0017-alcance-reducido-postes-luminaria-y-red-mt.md)

## Decisión

| id | clase | estado |
|---:|---|---|
| 5 | `poste_bt` | activa: fuste, ménsulas, crucetas y, si la hay, la luminaria con su pastoral |
| 12 | `poste_mt` | activa: lo mismo, para el poste de media |
| 13 | `luminaria` | **obsoleta** |
| 9 | `conductor_mt` | **en espera** |

Un poste con luminaria se recorta **entero, en un solo archivo**, con la clase
del poste. Las demás clases siguen `en_espera` con su id congelado y se
retomarán en una fase posterior.

## Por qué

**El objeto que se cuenta es el poste.** El inventario pregunta cuántos postes
hay y de qué tipo. Con la luminaria como clase aparte, un poste de BT con
luminaria eran dos recortes, y el límite entre ambos (donde el pastoral se
separa del fuste) era un corte convencional, ambiguo en 2-3 cm. Era esfuerzo de
anotación sobre una frontera que el resultado no necesita.

**Con poca verdad de campo, menos clases.** Al cerrar esta revisión hay ~30
postes BT etiquetados en un bloque. Repartirlos entre poste y luminaria deja
dos clases con pocos ejemplos donde podría haber una con suficientes.

**Por qué no se recupera la clase 11 `pole_lv_light`.** Dividir el poste según
lleve luminaria duplicaría cada clase de poste (0017 explica por qué se
descartó). Si más adelante interesa saber si un poste lleva luminaria, será un
atributo del objeto poste, no una clase de punto.

**La red de MT sale del alcance.** Es la clase más fácil de anotar, pero no es
un poste, y esta fase se centra en un solo objeto.

## Por qué 13 queda obsoleta y no en espera

`en_espera` significa «volverá con esta misma definición». La luminaria no
vuelve así: si regresa, será como atributo o con otro criterio. El id 13 se
quema para poder seguir leyendo las anotaciones hechas entre 0017 y 0023 sin
confundirlas con una clase futura.

## Consecuencias

- `etapa_3_preparacion/herramientas/registrar_anotacion.py` rechaza `__luminaria.laz` y explica cómo
  rehacerlo: unir el recorte con el del fuste y guardarlo como `__poste_bt` o
  `__poste_mt`.
- `TARGET_IDS` pasa a `(5, 12)`. La métrica y los pesos de clase del
  entrenamiento se calcularán sobre esas dos clases.
- Siguen en pie las reglas de 0015 sobre qué ferretería es parte del poste.

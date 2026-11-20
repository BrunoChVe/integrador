# 0020 — Tres etapas, y se anota sin borrador

- **Estado:** aceptada
- **Fecha:** 2026-10-03
- **Afecta a:** `dvc.yaml`, `params.yaml`, `src/stages/`, `src/common/`,
  `tools/`, `requirements.txt`, `README.md`, `notebooks/`
- **Origen:** al recortar el alcance a cuatro clases (0017) y mover la
  anotación al bloque de 200 m (0018), la mitad del pipeline se quedó sin
  consumidor. Mantenerlo tenía un coste y ninguna ventaja.
- **Continúa a:** [0017](0017-alcance-reducido-postes-luminaria-y-red-mt.md),
  [0018](0018-el-bloque-de-anotacion-sustituye-a-la-tesela.md)

## Decisión

Dos decisiones, y la segunda se sigue de la primera.

**1. Se anota sobre la nube completa, sin preetiqueta.** No hay borrador
geométrico. El anotador abre el bloque de 200 m a resolución completa en
CloudCompare y recorta los activos.

**2. El pipeline baja de ocho etapas a tres:** `eda`, `catalog`, `bloques`.
Se borran `ground`, `clean`, `features`, `weak_labels` y `dataset`, más
`src/common/geometry.py`, `src/viewer/`, `tools/vista_limpia.py`,
`tools/generar_guia.py`, `tools/diagnostico_postes.py`,
`tools/colorear_clases.py`, `tools/check_acceptance.py`,
`tools/regenerar_eda.py`, las tres guías HTML generadas y tres de los cuatro
notebooks. Siguen en el historial de git.

## Por qué

**Las cuatro etapas intermedias existían para una cosa.** Ajustar el suelo,
limpiar, calcular rasgos multiescala y aplicar reglas geométricas servían para
producir el borrador que alguien iba a corregir. Esa era su única salida útil:
nada más las consumía. Sin borrador no tienen destinatario.

**El borrador no estaba ayudando donde hace falta.** Medido sobre las 36
teselas de la última corrida (22.9 M puntos voxelizados, `reports/weak_labels.json`),
las clases del alcance actual eran el **0.23 %** de los puntos:

| clase | puntos | % |
|---|---:|---:|
| `pole_lv_light` | 23 685 | 0.104 |
| `pole_lv` | 16 743 | 0.073 |
| `conductor_mv` | 12 834 | 0.056 |
| `pole_mv` | 798 | 0.003 |

Frente a `building` 34.5 %, `road` 28.7 % y `unclassified` 26.2 %. El borrador
era bueno en las clases de superficie —las que ya no interesan— y marginal en
los activos. Y `pole_mv` con 798 puntos no era mala suerte: era un **error**
que el propio código escondía, que la máscara de proximidad a conductores de MT
se construía contra la clase equivocada y nunca se disparaba. Es decir, en la
clase más valiosa del alcance el borrador aportaba casi nada y lo que aportaba
estaba mal.

**Un borrador malo es peor que ninguno.** El argumento de 0005 era que corregir
va ~10× más rápido que pintar de cero. Eso vale cuando el borrador acierta la
mayor parte. Con 0.003 % de acierto en `pole_mv`, lo que produce es trabajo de
revisión sobre falsos positivos y, peor, la tentación de aceptar lo que ya está
pintado. El sesgo de confirmación sobre una preetiqueta mala contamina la verdad
de campo, que es el único activo que este capstone está construyendo.

**Y se perdían puntos.** Para llegar al borrador había que voxelizar a 5 cm
(factor 2.85) y aplicar SOR y filtros de clúster. Para un poste, y sobre todo
para la red, esos puntos importan: el bloque a resolución completa trae 751
pts/m² medidos y la nube voxelizada 264. Anotar sobre el crudo es anotar sobre
lo que de verdad entregó el sensor.

**La máscara de revisado de 0016 deja de hacer falta.** Existía para distinguir,
dentro de un archivo que contenía la tesela entera, lo que una persona había
mirado de lo que había rellenado el borrador. Sin borrador la distinción
desaparece: `annotation_revisada/` guarda **solo los puntos recortados**, todo
punto del archivo es verdad de campo por construcción, y lo que no está
simplemente no se ha mirado. Pesa KB en vez de GB, y se puede subir al remoto
sin pensarlo.

## Lo que esto cuesta

Es un recorte, y conviene decir qué se pierde:

- **Hay que pintar de cero.** Es más lento por bloque que corregir un borrador
  bueno. Se acepta porque el borrador no era bueno en estas clases.
- **No hay rasgos geométricos.** Cuando se escriba el entrenamiento habrá que
  decidir si el modelo come la nube cruda —que es lo que hacen RandLA-Net y una
  U-Net dispersa— o si hace falta volver a calcular PCA local. Antes esa
  decisión estaba tomada aguas arriba y ahora no lo está. Es una ventaja
  disfrazada de pendiente: `docs/architecture/seleccion-de-red.md` daba el vóxel
  de 5 cm por fijado, y ya no lo está.
- **No hay altura sobre el suelo.** Era el rasgo más útil del conjunto y
  separaba casi solo poste de BT de poste de MT. Al anotar no se echa de menos
  —un humano ve la altura— pero al entrenar habrá que recuperarlo.
- **Varios ADR describen código que ya no existe**: 0003 (suelo antes de
  limpiar), 0004 (el SOR destruye los cables), 0006 (rasgos multiescala), 0008
  (umbral de confianza), 0010 (clase área verde), 0013, 0014, 0015 y 0016. Se
  conservan a propósito: explican por qué se hicieron y, leídos junto a este,
  por qué se quitaron. Borrarlos dejaría el repositorio limpio y la historia
  falsa.

## Sin resolver

- El entrenamiento no está escrito. Se escribirá cuando haya verdad de campo
  suficiente, y mirando el recuento **por clase** de
  `registrar_anotacion.py --estado`, no el total: tres postes de MT y mil de BT
  suman muchos puntos y no entrenan nada.
- Cuántos bloques hay que anotar para que las cuatro clases den para entrenar.
  No se sabe y no se va a adivinar: se anota, se mide el recuento por clase y se
  decide con el dato.
- Si el borrador vuelve, vuelve al revés: entrenado sobre la verdad de campo que
  se está construyendo y aplicado a bloques sin anotar, que es aprendizaje
  activo y no una cascada de umbrales. Esa es la forma en la que una preetiqueta
  sí ayuda.

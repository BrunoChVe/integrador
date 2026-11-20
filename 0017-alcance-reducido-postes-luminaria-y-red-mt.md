# 0017 — Alcance reducido: poste, luminaria y red de media tensión

- **Estado:** aceptada (los pesos de clase quedan **sin resolver**)
- **Fecha:** 2026-10-03
- **Afecta a:** `params.yaml: ontology` (v6), `params.yaml: weak_labels`,
  `src/stages/s06_weak_labels.py`, `src/stages/s07_dataset.py`,
  `tools/migrar_ontologia.py`, `docs/manual_anotacion.html`
- **Origen:** al medir el borrador sobre las 36 teselas quedó claro que las
  clases que el cliente factura son una fracción minúscula de los puntos, y que
  anotar doce clases a la vez reparte el esfuerzo humano justo donde no está el
  activo.
- **Sustituye en parte a:** [0014](0014-tres-clases-de-poste.md), cuya clase 11
  `pole_lv_light` queda obsoleta, y a
  [0013](0013-tres-niveles-de-conductor-y-arboles.md), cuyos tres niveles de
  conductor dejan de etiquetarse los dos de abajo.


> **Nota posterior.** Este registro se escribió antes de
> [0020](0020-tres-etapas-y-sin-borrador.md), que borró el borrador
> geométrico y cinco de las ocho etapas. Las partes que hablan de
> `s06_weak_labels.py`, `s07_dataset.py` o `tools/vista_limpia.py`
> describen código que ya no está en el árbol de trabajo, aunque sigue
> en el historial de git. Lo que se decidió aquí sobre la ontología y
> la rejilla sigue vigente.

## Decisión

El alcance de esta fase se recorta a **cuatro clases activas**:

| id | Clase | Qué es |
|---|---|---|
| 5 | `pole_lv` (`poste_bt`) | poste de baja, con o sin luminaria encima |
| 12 | `pole_mv` (`poste_mt`) | poste de media |
| 13 | `luminaire` (`luminaria`) | pastoral más bloque de la luminaria, **nueva** |
| 9 | `conductor_mv` (`conductor_mt`) | red de media tensión |

Las otras ocho pasan a **`en_espera`** con su id congelado. La clase 11 pasa a
**`obsoleta`**. La ontología sube a v6.

**La numeración NO se toca.** El id es literalmente lo que se escribe en el
campo LAS `classification`, así que renumerar invalida toda anotación ya
registrada y cualquier checkpoint. En su lugar cada clase lleva ahora un campo
`estado` con tres valores —`activa`, `en_espera`, `obsoleta`— y las etapas
filtran por él. Reactivar una clase es cambiar una palabra en `params.yaml`.

## Por qué: el activo es el 0.23 % de los puntos

Medido en el borrador actual (`reports/weak_labels.json`, 36 teselas,
22.9 M puntos voxelizados):

| Clase | Puntos | % del total |
|---|---|---|
| `pole_lv` | 16 743 | 0.073 % |
| `pole_lv_light` | 23 685 | 0.104 % |
| `pole_mv` | 798 | 0.003 % |
| `conductor_mv` | 12 834 | 0.056 % |
| **suma de los activos** | **54 060** | **0.23 %** |
| `building` | — | 34.5 % |
| `road` | — | 28.7 % |
| `unclassified` | — | 26.2 % |

Dicho de otra forma: el 90 % de los puntos de la escena son suelo, fachada y
ruido. Anotar doce clases a la vez obliga al anotador a repasar pista, vereda,
fachada y área verde —clases de superficie, fáciles para la regla y abundantes—
antes de llegar a los 54 000 puntos que son el activo. Esas clases de superficie
no son lo que el cliente factura, y el tiempo humano es el recurso escaso del
proyecto.

## Por qué estas cuatro y no otras

**El poste es la unidad del inventario.** Es lo que se cuenta, lo que se
geolocaliza y lo que ancla la red: sin poste no hay fila en el entregable. Todo
lo demás es atributo de un poste o un tramo entre dos.

**La red MT es el conductor más fácil de los tres niveles.** Va en tres fases
con separación medida de 0.3 a 3.4 m (ver [0019](0019-la-tesis-base-y-que-superamos.md))
y por encima de todo lo demás de la calle. La BT autoportante, en cambio, se ve
como una sola línea y se confunde con telecom, que es exactamente el par que
0013 declaró sin resolver. Meter en el alcance la clase cuya frontera no
sabemos trazar sería comprar el problema abierto en vez del activo.

## Por qué la luminaria es clase propia y no un tipo de poste

0014 la modeló como atributo del poste: la clase 11 era «poste de baja **con**
luminaria». Eso falla por dos lados.

**Duplica las clases de poste.** La luminaria se instala indistintamente sobre
poste de BT y sobre poste de MT. Como atributo del poste hacen falta
`pole_lv`, `pole_lv_light`, `pole_mv`, `pole_mv_light`... y la clase 11 era
exactamente esa duplicación empezada a medias.

**No se puede contar.** El inventario mide puntos de alumbrado. Con la
luminaria dentro de la clase del poste, la predicción no deja sacar cuántos
puntos son alumbrado y cuántos fuste: la información se perdió en la etiqueta.

De ahí la clase 13, que es el **conjunto**: pastoral más bloque. Consecuencia
asumida: la clase 11 queda `obsoleta`, su id **se quema y no se reutiliza** —hay
anotaciones registradas que lo contienen—, y esas anotaciones se reparten entre
5 (fuste) y 13 (alumbrado).

**Dónde se corta el límite poste/luminaria:** donde el pastoral se separa del
fuste. Es un corte convencional y es ambiguo en 2-3 cm de puntos. Se acepta
explícitamente; no hay una frontera física mejor que ofrecerle al anotador.

**La ménsula sigue siendo poste, y no es luminaria.** [0015](0015-la-mensula-es-parte-del-poste.md)
ya la metió en la clase del poste y ese criterio no cambia. Las tres señales de
0015 siguen siendo el discriminante:

| | Ménsula (clase 5 o 12) | Pastoral (clase 13) |
|---|---|---|
| Alcance desde el eje | 0.2–0.8 m | más de 1.0 m |
| Extremo | hierro de sección constante | acaba en **bloque** |
| Conductores en la punta | sí, de ahí sale la BT | no cuelga nada |

## Por qué `conductor_lv` se sigue calculando aunque esté en espera

La tercera señal de la tabla es la buena, y depende de una clase que acaba de
salir del alcance. Por eso el id 6 está `en_espera` pero su máscara **se sigue
calculando en memoria, sin etiquetarse**: es la señal negativa que distingue
ménsula de pastoral. Sin ella la clase 13 pierde su mejor discriminante y se
queda con las dos señales débiles.

Es la única excepción. El resto de clases en espera no se calculan.

## La consecuencia incómoda: `unclassified` pasa del 26 % al 95 %

Todo lo que sale del alcance cae en la clase 0. Pasa de 26.2 % a **más del
95 %** de los puntos. Hay que declararlo porque cambia dos cosas:

- La clase 0 sigue siendo `ignore_id`, fuera de la pérdida y de la mIoU. Eso
  era higiene con doce clases; con cuatro es lo que hace que el problema exista.
  El modelo no se entrena para acertar «no es nada», se entrena para encontrar
  los cuatro activos.
- Los pesos de clase de la etapa 07 son `1/sqrt(freq)` (`dataset.class_balance:
  inverse_sqrt_frequency`). Con cuatro clases entre el 0.003 % y el 0.1 %, esa
  fórmula da pesos extremos, y `pole_mv` —798 puntos— saldría con un peso que
  convierte cada uno de sus puntos en una palanca. **Hay que revisar
  `class_balance`; queda pendiente.**

## Cómo se hace

- `params.yaml: ontology` — campo `estado` por clase, versión 6. Las clases
  activas van primero; las obsoletas y las en espera, en bloques separados con
  su comentario.
- `s06_weak_labels.py` — recorre solo las clases `activa`, con la excepción de
  `conductor_lv` descrita arriba.
- `s07_dataset.py` — filtra por `estado` al construir la tabla, de modo que una
  clase en espera no aparezca ni con cero puntos.
- `tools/migrar_ontologia.py` — reparte las anotaciones con clase 11 entre 5
  y 13.

## Debilidades conocidas

- **El reparto automático de la clase 11 en 5 + 13 no está resuelto.** Hay tres
  teselas registradas con esa clase. La separación tiene que apoyarse en el
  mismo detector de brazo que ya corre en el borrador, y eso significa que una
  anotación humana acabaría troceada por una regla. Mientras no se mida cuánto
  acierta, lo honesto es revisarlas a mano.
- **Los pesos de clase.** Ver arriba. Es el riesgo más concreto de este ADR:
  pasar de doce a cuatro clases no mejora el entrenamiento por sí solo si el
  balanceo se desboca.
- **7.5 m como corte de MT está sin validar.** Es el umbral que bajamos en
  [0019](0019-la-tesis-base-y-que-superamos.md) y gobierna la frontera entre la
  única clase de conductor activa y la BT, que ya no se etiqueta. Si está mal,
  el error es sistemático y no hay clase vecina etiquetada que lo delate.
- **`pole_mv` sigue casi vacía** —798 puntos en 36 teselas— y ahora es una de
  cuatro clases en vez de una de doce. Sigue siendo lo primero que hay que
  buscar al anotar.
- **Reactivar una clase no es gratis aunque el id esté congelado.** El estado se
  cambia en una línea, pero su regla de borrador lleva meses sin ejecutarse
  contra datos nuevos, y los pesos se vuelven a recalcular.

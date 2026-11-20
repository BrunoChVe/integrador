# 0016 — Anotación por zonas y máscara de revisado

- **Estado:** aceptada
- **Fecha:** 2026-09-20
- **Afecta a:** `tools/vista_limpia.py`, `tools/registrar_anotacion.py`,
  `src/common/anotacion.py` (nuevo), `src/stages/s07_dataset.py`, `dvc.yaml`
- **Origen:** al empezar a anotar cables quedó claro que la tesela de 40 m parte
  los vanos. Al implementar la solución apareció un segundo problema, más grave,
  en cómo la etapa 07 leía las teselas revisadas.

## Decisión

**1. Los cables se anotan por ZONAS, no por teselas.** Una zona es un grupo de
teselas vecinas del mismo escaneo, partido en bloques de 3×3 teselas (120 m) si
es más grande. `vista_limpia.py --zonas` escribe un archivo por zona, con un
anillo de una tesela de contexto alrededor. El recorte se guarda como
`<zona>__<clase>.laz` y `registrar_anotacion.py` lo reparte a cada tesela que
toque.

**2. Cada tesela revisada lleva una máscara `revisado`.** Una dimensión extra
del LAS que vale 1 solo en los puntos que tocó un recorte humano. Solo esos
cuentan como verdad de campo; el resto sigue siendo borrador.

## Por qué 1: la tesela parte los vanos

El vano es la unidad natural de un cable —su catenaria, su flecha y su altura
de amarre son lo que distingue BT de telecom (conversación de 0015)—, y la
tesela de 40 m lo corta:

| | Longitud típica | Cortado por una tesela de 40 m | Por una zona de 120 m |
|---|---|---|---|
| Vano BT | ~30 m | ~75 % | ~25 % |
| Vano MT | 50–70 m | **siempre** — es más largo que la tesela | ~50 % |

*(Probabilidad de que un tramo de longitud L caiga sobre un borde de una rejilla
de paso B: L/B para L < B. Longitudes del conocimiento de campo del equipo.)*

Un vano cortado se decide dos o tres veces, sin ver nunca la catenaria entera,
y nada garantiza que las decisiones coincidan.

**Por qué componentes conexas y no una rejilla fija.** Las teselas
seleccionadas no forman una rejilla continua: son manchas separadas por huecos
sin datos. Si la zona es una mancha, su borde cae donde se acaban los datos, y
ahí no se corta ningún vano porque no hay nada al otro lado. Solo las manchas
grandes se parten, y para ese corte está el anillo de contexto: con una tesela
(40 m) se ve entero cualquier vano de BT que cruce el borde y la mayor parte de
uno de MT.

**Por qué no el escaneo entero.** Se consideró: cero vanos cortados. Pero un
escaneo completo es mucho para revisar de una sentada, un error de rectángulo
se propaga a docenas de teselas, y no escala al conjunto completo de 18 000
teselas. La zona es el compromiso. `--max-teselas 0` sigue permitiendo
componentes enteras sin partir, y el registro acepta igual un recorte de
escaneo completo (`<escaneo>__<clase>.laz`).

**Dos detalles que la implementación no puede olvidar.**

- *El anillo de 5 m de cada tesela.* El borrador guarda en cada tesela su
  núcleo de 40 m más 5 m de contexto, así que un punto de la franja compartida
  está en dos teselas. La vista de zona toma solo núcleos —si no, esa franja
  saldría duplicada—, y el registro reparte a cada tesela mirando su extensión
  CON anillo —si no, el punto quedaría corregido en una tesela y no en la
  vecina—.
- *Los grupos se calculan sobre la zona entera*, no tesela a tesela. Es lo que
  hace que un vano salga como un solo grupo aunque cruce tres teselas, y es la
  segmentación de instancias que necesitarán después los rasgos por vano.

## Por qué 2: registrar un poste convertía un millón de puntos en verdad

`registrar_anotacion.py` guarda la tesela revisada **entera**, con todos sus
puntos, para que CloudCompare la abra como cualquier otra. Hasta aquí bien. El
problema estaba en la etapa 07: todo punto de una tesela revisada recibía
`label_confidence = 1.0` y `label_is_draft = False`.

La primera anotación del proyecto lo deja a la vista. Se registró un poste
—3 258 puntos— en `t_7329_216705`, y la etapa 07 habría contado como verdad de
campo los **1 170 298** puntos de la tesela. `puntos_revisados_a_mano` en
`reports/dataset.json` habría dicho 1 170 298.

Con recortes de zona el error se multiplica: un solo vano de MT toca tres o
cuatro teselas, y convertiría en «verdad» varios millones de puntos de
borrador. Y la validación —el escaneo 502— acabaría midiendo cuánto se parece
el modelo a las reglas de la etapa 06, que es exactamente la trampa que el
README declara querer evitar.

Había además un segundo efecto, más sutil: los puntos no tocados de una tesela
revisada guardaban la etiqueta de borrador **del momento del registro**. Al
regenerar el borrador —como pide 0015 para los postes— esas etiquetas viejas
seguirían mandando sobre las nuevas.

Con la máscara, las dos cosas se resuelven a la vez: donde una persona tocó,
manda su clase y la confianza es 1.0; en el resto manda el **borrador actual**
con su confianza de regla.

## Cómo se hace

- `src/common/anotacion.py` — nuevo. Un solo sitio que sabe leer una tesela
  revisada (`aplicar_revisada`), calcular las zonas (`zonas_de_escaneo`) y la
  extensión de una tesela con su anillo (`extension_tesela`). Lo usan las tres
  herramientas, para que no puedan discrepar.
- `vista_limpia.py --zonas <escaneo>` — un archivo por zona, con los campos
  escalares `grupo`, `revisado`, `nucleo` (1 = de la zona, 0 = contexto),
  `tesela_ix` y `tesela_iy`. De paso, `--color foto` escribe a su propio
  archivo (`..._foto.laz`) en vez de machacar la vista por clase.
- `registrar_anotacion.py` — acepta `<zona>__<clase>.laz` y `<escaneo>__<clase>.laz`,
  reparte a las teselas que toque, escribe la máscara, e informa de la
  cobertura del recorte: si no empareja casi nada, avisa del global shift.
  `--estado` muestra el % revisado de cada tesela.
- `s07_dataset.py` — lee las revisadas con `aplicar_revisada`. `dvc.yaml`
  añade `src/common/anotacion.py` como dependencia de la etapa `dataset`.

Probado sobre un repositorio sintético con el mismo formato de tesela: un vano
que cruza cuatro teselas sale como un grupo, se registra de una vez, se corrige
en ambas teselas de cada franja compartida, y solo sus puntos quedan marcados.

## Migración

Los archivos registrados antes de 0016 no traen la máscara. Para ellos
`aplicar_revisada` deduce: cuenta como revisado lo que difiere del borrador. Se
pierden las confirmaciones —imposibles de distinguir en un archivo viejo— pero
no se inventa verdad. Para pasar un archivo al formato nuevo basta con volver a
registrar su recorte original:

```
python tools/registrar_anotacion.py recortes/t_7329_216705__pole_lv_light.las
```

## Debilidades conocidas

- **Tesela completa** (el modo sin sufijo de clase): no hay forma de saber qué
  miró la persona, así que la máscara solo marca lo que cambió. Las
  confirmaciones se pierden. Para cables, usar recortes.
- **Las zonas partidas siguen cortando vanos** en sus bordes internos. El
  anillo los deja ver enteros, pero la parte que cae en el anillo se decide
  mirando desde la zona vecina. No hay incoherencia —el registro reparte cada
  punto a su tesela y el último recorte manda—, solo trabajo repetido.
- **Memoria.** Una zona de 3×3 con anillo son hasta 25 teselas; la vista limpia
  carga cada una, se queda con lo aéreo (~13 %) y la suelta. En un portátil de
  16 GB sobra, pero `--max-teselas` alto con `--anillo 2` puede no caber.
- **La tolerancia de emparejamiento** sigue siendo 2 cm
  (`dataset.annotation.tolerancia_m`). El registro de la primera anotación
  emparejó 3 258 de 3 258 puntos, así que el ida y vuelta por CloudCompare no
  mueve coordenadas.

# 0018 — El bloque de 200 m sustituye a la tesela y a la zona

- **Estado:** aceptada (el ajuste del suelo sobre 200 m queda **sin resolver**)
- **Fecha:** 2026-10-03
- **Afecta a:** `params.yaml: tiling`, `src/stages/s02_bloques.py` (renombrado
  desde `s02_tile.py`), `src/common/anotacion.py`, `src/common/config.py`,
  `src/stages/s07_dataset.py`, `tools/vista_limpia.py`,
  `tools/registrar_anotacion.py`, `dvc.yaml`
- **Origen:** anotar con la zona de [0016](0016-anotacion-por-zonas-y-mascara-de-revisado.md)
  destapó que el problema no era el tamaño de la vista, sino que la misma rejilla
  de 40 m servía para guardar, para anotar y para entrenar. Y que el acelerador
  de la etapa 02 era la causa real del «se pierden puntos».
- **Sustituye a:** [0016](0016-anotacion-por-zonas-y-mascara-de-revisado.md) en
  su punto 1 — la zona desaparece. La máscara `revisado` se mantiene intacta.


> **Nota posterior.** Este registro se escribió antes de
> [0020](0020-tres-etapas-y-sin-borrador.md), que borró el borrador
> geométrico y cinco de las ocho etapas. Las partes que hablan de
> `s06_weak_labels.py`, `s07_dataset.py` o `tools/vista_limpia.py`
> describen código que ya no está en el árbol de trabajo, aunque sigue
> en el historial de git. Lo que se decidió aquí sobre la ontología y
> la rejilla sigue vigente.

## Decisión

Se separan dos rejillas que hasta la v5 eran la misma:

| | Parámetro | Paso | Se materializa en disco | Para qué |
|---|---|---|---|---|
| **Bloque** | `tiling.bloque_m` | 200 m | sí, es la unidad de `interim/` | almacenamiento y anotación |
| **Tesela** | `tiling.tesela_m` | 40 m | **no** | entrenamiento, se corta en la etapa 07 |

El bloque es lo que se abre, lo que se recorta y lo que se guarda: un solo
archivo para las tres cosas. La tesela de 40 m deja de existir como archivo y
pasa a ser un corte en memoria de la etapa dataset.

## Por qué: 40 m parte los objetos

Un vano de MT mide 50-70 m —el CNE Suministro 2011 fija el vano máximo en
70 m—, así que a 40 m sale cortado **siempre**. Decidir su clase dos o tres
veces sin ver nunca la catenaria entera es la causa principal de error de
anotación medida hasta ahora.

El parche fue la zona de 0016: agrupar teselas vecinas al **ver** para volver a
partirlas al **registrar**. Eso costó tres funciones de componentes conexas
—`zonas_de_escaneo`, `nombre_zona`, `anillo_de_zona`— y una convención de
nombres propia, `<escaneo>_z<ix>_<iy>`, que no correspondía a ningún archivo del
repositorio. Con el bloque de 200 m nada de eso hace falta. Las tres funciones
se han **borrado** de `src/common/anotacion.py`.

El argumento original de la tesela única era «así las tres rejillas no pueden
discrepar». Costaba más de lo que daba: lo que no podían discrepar eran tres
usos con requisitos distintos, forzados al mismo paso.

## El acelerador era el verdadero culpable de «se pierden puntos»

`max_tiles_per_scan: 12` con `tile_selection: densest` no elegía un recorte del
área: elegía **12 manchas sueltas por escaneo**.

| | |
|---|---|
| Teselas materializadas | 36 (3 escaneos × 12) |
| Puntos en ellas | 43 M |
| Puntos del escaneo completo de ate | 421 M |
| Forma de la selección | manchas separadas por huecos, **sin rejilla continua** |

Esa última fila es la que explica 0016: las componentes conexas eran necesarias
*porque la selección no era contigua*. Los puntos no se perdían en el corte de
la rejilla; no se materializaban nunca. Ahora `max_bloques_por_escaneo: 0` =
todos.

## Por qué 200 m y no otro número

La razón del tamaño es que **cabe entero un vano de MT de 70 m**. Lo demás era
comprobar que el archivo resultante se puede manejar a mano.

| Tamaño | Puntos por bloque | Veredicto |
|---|---|---|
| Archivo crudo tal cual | 0.4-8.4 M, huellas de 50-200 m | **descartado**: los archivos se solapan entre pasadas y el mismo poste sale en 2-3 archivos — se anotaría dos veces |
| 200 m | ver medida abajo | **elegido** |
| 400 m | mediana 6 M, p90 23 M, máximo 44 M (estimado desde cabeceras) | las tijeras de CloudCompare van lentas |

**Medido sobre la corrida real** (`reports/bloques.json` y
`bloque_index.csv`, los 3 escaneos de ate, 421 156 950 puntos):

| | puntos por bloque, anillo incluido |
|---|---:|
| mínimo | 2 586 |
| mediana | 3 764 816 |
| p90 | 12 234 455 |
| máximo | 29 058 467 |

101 bloques escritos de los 125 planificados: los 24 que faltan son celdas que
el planificador propone porque la caja envolvente de algún archivo las toca,
pero por las que la trayectoria no pasó, así que salen vacías. **La suma de los
núcleos da 421 156 950 puntos, exactamente el total del catálogo: diferencia
cero.** Es la comprobación que importa, porque el motivo del cambio era
precisamente que antes no se materializaban todos los puntos.

La mediana de 3.8 M es cómoda en CloudCompare. **El extremo no lo es**: hay un
bloque de 29 M y unos cinco por encima de 18 M, todos en cruces donde se
superponen varias pasadas. Se abren, pero las tijeras van lentas. No se parten
por ahora —son el 5 % de los bloques y la rejilla uniforme vale más que el caso
peor— pero si anotar ahí resulta impracticable, lo correcto es bajar
`bloque_m` a 100 m para ese escaneo y no inventar una excepción: la rejilla de
100 m también es múltiplo de la tesela de 40... no lo es, 100/40 = 2.5, así que
habría que ir a 80 m o a 120 m. Queda anotado para cuando se mida de verdad.

**`bloque_m` tiene que ser múltiplo de `tesela_m`** para que el borde de una
tesela nunca cruce un bloque: 200/40 = 5×5 teselas. La etapa 02 lo comprueba
**al arrancar**, no al final de un proceso de horas.

**El anillo de contexto sube de 5 a 10 m.** Nació para que un rasgo calculado
junto al borde no viera un vecindario truncado, y tenía que superar con holgura
el radio de rasgo más grande (2.0 m). Con los rasgos fuera del repositorio
([0020](0020-tres-etapas-y-sin-borrador.md)) le queda otra razón, igual de
buena: **un poste justo en el borde sale partido entre dos bloques**, y con
10 m de solape se ve entero en los dos y se puede anotar en cualquiera. Sobre
200 m son solo un 10 % de solape, frente al 25 % que suponían 5 m sobre una
tesela de 40 m.

## Los nombres pasan de `t_<ix>_<iy>` a `b_<ix>_<iy>`

A propósito. Un `t_7322_216695` indexaba la rejilla de 40 m y cubre otro suelo
distinto del que cubriría el mismo índice en la rejilla de 200 m. Con prefijos
distintos es imposible mezclar las dos rejillas por descuido.

Consecuencia asumida: las 3 teselas ya anotadas en `annotation_revisada/`
quedaban sobre la rejilla vieja. Se descartaron —eran 2 795 puntos de conductor
de BT, hoy fuera de alcance, y 5 437 de la clase 11, hoy obsoleta— en vez de
intentar migrarlas: partir la clase 11 en fuste y alumbrado con una regla
geométrica habría sido **inventar verdad de campo**, que es justo lo que este
proyecto declara no hacer.

## Coste medido de la cobertura completa

La estimación era de ~4.5 h de CPU y ~50 GB, extrapolando las cinco etapas de
la corrida anterior (42 min para 36 teselas y 65 M puntos). La realidad fue
mucho mejor, porque con la poda de
[0020](0020-tres-etapas-y-sin-borrador.md) solo queda el corte:

| | medido |
|---|---|
| tiempo | **827 s** (13.8 min) para los 421 M puntos |
| disco | **3.8 GB** en `data/interim/01_bloques` |
| bloques | 101 escritos, 125 planificados |
| puntos de núcleo | 421 156 950 — el total del catálogo, diferencia **cero** |

Es decir, el acelerador `max_tiles_per_scan` no sobraba solo por el disco: una
vez fuera las cuatro etapas que de verdad costaban, la cobertura completa cabe
en un café.

## Cómo se hace

- `params.yaml: tiling` — `bloque_m: 200`, `tesela_m: 40`, `buffer_m: 10`,
  `max_bloques_por_escaneo: 0`. Desaparecen `max_tiles_per_scan` y
  `tile_selection`.
- `s02_tile.py` → `s02_bloques.py` — escribe bloques, comprueba la
  divisibilidad al arrancar y ya no selecciona nada.
- `src/common/anotacion.py` — fuera `zonas_de_escaneo`, `nombre_zona` y
  `anillo_de_zona`, la maquinaria de zonas de 0016 que el bloque deja sin
  sentido. Quedan `indice_bloque`, `nombre_bloque`, `extension_bloque` y
  `bloques_vecinos`.
- `src/common/config.py` — `PATHS.bloques` apunta a `data/interim/01_bloques`.
- `tools/registrar_anotacion.py` — trabaja sobre el bloque y reparte cada
  recorte a todos los bloques donde caiga; se va el modo `--zonas`.
- `dvc.yaml` — la etapa pasa a llamarse `bloques`.

La tesela de 40 m no la corta nadie todavía: la etapa que lo hacía se borró con
el resto ([0020](0020-tres-etapas-y-sin-borrador.md)) y el corte se escribirá
con el entrenamiento. Lo que 0018 fija es que **se puede** cortar, porque las
dos rejillas comparten origen y `bloque_m` es múltiplo de `tesela_m`.

## Debilidades conocidas

- **El ajuste del suelo sobre 200 m.** `ground.cloth_grid` ajusta una rejilla de
  1 m, y 200 m de calle con pendiente son un área **25 veces mayor** que la
  tesela de 40 m sobre la que se calibró. El riesgo de que la pendiente arrastre
  el nivel de suelo es real y hay que medirlo. Ver el hallazgo de la
  voxelización por `gps_time` en [0019](0019-la-tesis-base-y-que-superamos.md):
  es el candidato número uno si la altura sobre el suelo sale mal en el bloque.
- **El corte de teselas en la etapa 07 aún no está escrito.** Hasta que lo esté,
  el repositorio produce bloques anotables pero no dataset de entrenamiento.
- **Hay que volver a recortar las 3 anotaciones existentes.** No se pierde el
  trabajo de clasificación —los recortes originales siguen ahí—, pero la
  correspondencia con la rejilla nueva se rehace a mano.

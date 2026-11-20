# 0014 — Tres clases de poste: MT, BT y BT con luminaria

- **Estado:** aceptada (reglas del borrador **provisionales**)
- **Fecha:** 2026-09-15
- **Afecta a:** `params.yaml: ontology` (v4), `params.yaml: weak_labels.poles`,
  `src/stages/s06_weak_labels.py`
- **Origen:** el equipo necesita distinguir el poste de media, el de baja
  desnudo y el de baja con alumbrado público; son activos distintos en el
  inventario y en la orden de trabajo.

## Decisión

La ontología pasa de once a **trece clases**. El id 5 se estrecha y se añaden
dos al final:

| id | Clase | Qué es |
|---|---|---|
| 5 | `pole_lv` (`poste_bt`) | poste de baja tensión **sin** luminaria. Antes era `pole`, cualquier poste |
| 11 | `pole_lv_light` (`poste_bt_luminaria`) | poste de baja **con** luminaria y pastoral |
| 12 | `pole_mv` (`poste_mt`) | poste de media tensión |

Los ids 0–10 se conservan, como manda [0010](0010-clase-area-verde.md).

## Las dos señales, y de dónde salen

Ambas vienen del conocimiento de campo del equipo, y ambas son geometría
medible, no color:

**Altura de columna.** El poste de media supera los **11 m**; el de baja llega
a **8 m**. Entre medias no hay casi nada, así que un corte en 9 m separa bien.
Se confirma con una segunda condición: **conductores de MT pasando junto a la
punta** —puntos ya etiquetados como `conductor_mv` a menos de 3 m del eje y a
la altura de la punta—. Cualquiera de las dos basta.

**El pastoral.** La luminaria cuelga de un tubo curvo que sale del poste cerca
de la punta y la sostiene a uno o dos metros del eje. En la nube eso son puntos
a **0.4–2.5 m del eje**, en los **2 m superiores** del poste, y —esto es lo que
importa— **concentrados a un solo lado**. Una fachada detrás del poste también
deja puntos cerca de la punta, pero repartidos alrededor. Se mide con la
resultante circular de los azimuts: si los puntos caben en un sector de 110°,
es un brazo; si se reparten, es una pared.

Los puntos del brazo se etiquetan también como `pole_lv_light`: el pastoral es
parte del activo, no ferretería suelta.

## Cómo se hace

Los puntos de poste que ya reclamaba la regla anterior se agrupan en postes
individuales con componentes conexas (`cluster_eps_m: 0.7`). Cada grupo se
decide en orden: primero MT por altura o por conductores; si no, luminaria por
el brazo lateral; si no, BT desnudo. Un poste no puede caer en dos clases.

## Debilidades conocidas

- **Un poste pegado a una fachada, o bajo una copa**, puede mostrar puntos a un
  solo lado de la punta y ser llamado `pole_lv_light` por error. La dispersión
  angular reduce el caso, no lo elimina.
- **El poste de MT se decide por altura** cuando no hay conductores de media
  detectados cerca. Un poste de baja anormalmente alto, o uno de media cuya
  punta quedó fuera de la tesela, se clasificarán mal.
- **Un poste partido en dos grupos** —por oclusión a media altura— se evalúa
  como dos postes cortos, y ninguno alcanza la altura de media.

## El filtro que hubo que añadir, y por qué

La primera ejecución delató un defecto que la regla anterior escondía. Al
agrupar los puntos de poste aparecieron **1 647 «postes» en 8 teselas** —unos
200 por tesela, cuando una manzana tiene tres o cuatro—, y el 80 % de los puntos
estaban en grupos de más de 1.2 m de radio. El mayor tenía 14 519 puntos, 25 m
de alto y 25 m de radio: una fachada.

La regla por punto —vertical, lineal, columna alta— también describe la esquina
de un edificio. Por eso ahora hay un **filtro por grupo**: un poste es delgado
(radio ≤ 0.6 m), alto (≥ 2.5 m) y tiene cuerpo (≥ 30 puntos). Lo que no lo
cumple se queda sin clasificar, que es la respuesta honesta.

El radio se mide en el **cuerpo** del poste, no en la punta: el de media lleva
cruceta, y medir el grupo entero lo descartaba por ancho. Con el grupo completo,
`pole_mv` salía en cero.

## Cifras del borrador

| Clase | Puntos |
|---|---|
| `pole_lv` | 16,743 |
| `pole_lv_light` | 23,685 |
| `pole_mv` | 798 |

Unos 500 puntos de poste por tesela, que a 5 cm de vóxel son dos o tres postes:
la cifra que cabe esperar. Antes del filtro eran 26 000 por tesela.

**`pole_mv` es casi una clase vacía.** Con 798 puntos en las 36 teselas, uno o
dos postes de media identificados. Es la primera que hay que revisar al anotar.

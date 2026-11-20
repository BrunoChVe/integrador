# 0015 — La ménsula es parte del poste

- **Estado:** aceptada (el discriminante ménsula/pastoral es **provisional**)
- **Fecha:** 2026-09-20
- **Afecta a:** `params.yaml: ontology` (v5), `params.yaml: weak_labels.poles`,
  `src/stages/s06_weak_labels.py`, `docs/manual_anotacion.html`
- **Origen:** anotando `t_7329_216705` apareció un poste de BT con luminaria y
  ménsulas que el borrador no había etiquetado en absoluto. Al mirar por qué,
  salieron dos problemas distintos: uno de criterio y otro de regla.
- **Sustituye en parte a:** [0014](0014-tres-clases-de-poste.md), que decía que
  la ferretería acoplada quedaba sin clasificar.

## Decisión

**1. El herraje acoplado es parte del poste.** Ménsulas, crucetas, pastoral y
herrajes se etiquetan con la clase del poste al que pertenecen —5, 11 o 12—, no
como clase 0. La clase 0 se queda solo con herraje suelto, sin poste
identificable al que asociarlo.

**2. Un poste de baja puede tener ménsula o no.** Eso no cambia su clase. Vale
igual para el poste con luminaria: puede llevar ménsula además del pastoral.

**3. El filtro de grupo mide el radio por franjas, no por máximo.**

**4. La clase 11 deja de decidirse por "hay brazo lateral".**

Los ids no cambian. La ontología sube a v5 porque cambia el criterio de
pertenencia, no la numeración.

## Por qué 1: la incoherencia de 0014

0014 dice del pastoral: *«Los puntos del brazo se etiquetan también como
`pole_lv_light`: el pastoral es parte del activo, no ferretería suelta»*. Pero
la descripción de la clase 5 decía lo contrario para el resto: *«Solo el
cuerpo; la ferretería acoplada queda sin clasificar»*.

No hay razón para tratarlos distinto. Para el inventario de activos, que es el
caso de negocio, la ménsula es tan parte del poste como el pastoral. Y un
criterio que incluye un herraje y excluye otro es imposible de aplicar de
forma consistente entre tres anotadores.

Hay además un argumento de datos: si el criterio depende de que el anotador
decida caso por caso, los puntos de la frontera reciben supervisión
contradictoria justo donde el modelo tiene que separar la clase 5 de la 11.

## Por qué 3: el máximo del radio perdía postes enteros

0014 añadió un filtro por grupo para matar los 1 647 «postes» que eran
fachadas. Mide el radio sobre el *cuerpo*, definido como `hag <= alto -
top_band_m`, o sea perdonando los 2 m superiores, porque el poste de media
lleva cruceta arriba.

El problema: una **ménsula que cuelgue más de 2 m por debajo de la punta** cae
dentro de esa medida. Si sobresale más de 0.6 m del eje, el grupo entero se
marca `"descartado"` y el poste desaparece del borrador.

Y desaparecer es peor que salir mal etiquetado, por dos motivos:

- Al anotar no se ve lo que falta. Un poste en gris entre puntos grises no
  llama la atención; un poste del color equivocado, sí.
- Un poste descartado **no entra en la lista de ejes** que protege a la regla
  de árbol (`pole_exclusion_radius_m`), así que su ferretería se la lleva la
  clase 10. Por eso en `t_7329_216705` el fuste sale gris salpicado de verde:
  es la huella de un poste descartado.

La medida nueva corta el grupo en rebanadas de 0.5 m, calcula el radio p90 de
cada una y se queda con la **mediana**. Un poste con ménsula: casi todas las
franjas a 0.2 m, una o dos a 0.8 → mediana 0.2, pasa. Una fachada: todas
anchas → mediana alta, se descarta. Se conserva además un límite sobre la
*fracción* de franjas anchas, para que una pared con un hueco estrecho no pase.

El eje también cambia: se estima sobre la **mitad inferior** de la columna. La
mediana del grupo entero la desplaza un brazo lateral pesado, y un eje corrido
infla el radio de todas las franjas.

## Por qué 4: el brazo dejó de ser señal de clase

Consecuencia directa de la decisión 1, y es el coste que hay que asumir. Hasta
ahora la clase 11 se decidía así: *¿hay puntos a 0.4–2.5 m del eje, cerca de la
punta, en un solo azimut?* Si la ménsula también es poste y también sobresale
lateralmente, esa pregunta la contestan que sí los dos tipos de poste.

El discriminante nuevo son tres señales, de la más barata a la más fiable:

| | Ménsula | Pastoral |
|---|---|---|
| **Alcance** desde el eje | 0.2–0.8 m | 1.0–2.5 m |
| **Masa en el extremo** | poca: hierro de sección constante | mucha: la luminaria es un bloque |
| **Conductores en la punta** | sí, de ahí cuelga la BT | no, de una luminaria no cuelga nada |

La tercera es la buena y además es gratis: los conductores ya están
etiquetados cuando corre la regla de poste, así que preguntar «¿hay puntos
`conductor_lv` a menos de 0.4 m del extremo del brazo?» no cuesta un cálculo
nuevo.

## Cómo se hace

En `src/stages/s06_weak_labels.py`:

- `eje_del_cuerpo()` — eje XY desde la mitad baja de la columna.
- `perfil_radial()` — radio p90 por franjas horizontales.
- `detectar_brazo()` — el herraje lateral, buscado **siempre** y sobre toda la
  mitad superior, no solo cuando se sospecha luminaria y no solo en los 2 m de
  arriba.
- `es_pastoral()` — las tres señales de la tabla.
- `clasificar_postes()` — devuelve `brazos` y `ejes` para todos los grupos, no
  solo para los de luminaria. El llamador añade el brazo a la máscara del
  poste sea cual sea su clase.

## Qué hay que vigilar cuando se regenere el borrador

**El reparto 5 frente a 11.** Con 0014 salía `pole_lv_light` 23 685 puntos
contra `pole_lv` 16 743. En una manzana urbana lo esperable es lo contrario:
hay más postes desnudos que con alumbrado. La hipótesis es que las ménsulas
altas se estaban leyendo como pastorales. **Si tras este cambio la proporción
no se da la vuelta, la hipótesis era falsa y hay que volver aquí.**

**Cuántos postes aparecen que antes no estaban.** `tools/diagnostico_postes.py`
cuenta los descartes por motivo sobre el borrador anterior. La diferencia entre
ese número y los postes nuevos es la medida directa de si este ADR sirvió.

**`pole_mv` sigue casi vacía** (798 puntos en 34 teselas). Este cambio no la
toca. Sigue siendo la primera clase a revisar al anotar.

## Debilidades conocidas

- **Un poste pegado a una fachada** puede seguir dando puntos a un solo lado y
  fabricar un brazo falso. La dispersión angular y el límite de masa en el
  extremo reducen el caso; no lo eliminan.
- **La ménsula sin conductores visibles** —ocluidos, o un vano que sale fuera
  de la tesela— cae en las dos primeras señales, que son las débiles.
- **El umbral de 1.0 m de alcance es de catálogo, no medido.** Habría que
  comprobarlo contra postes reales del distrito, igual que el umbral de altura
  de 0013 sigue pendiente de validar.
- **Dos ménsulas apiladas** pueden sumar suficientes franjas anchas para
  superar `max_fraccion_franjas_anchas` en un poste corto con pocas franjas.

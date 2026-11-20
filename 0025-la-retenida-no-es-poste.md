# 0025 — El brazo de la retenida es poste; el cable de la retenida, no

- **Estado:** aceptada
- **Fecha:** 2026-10-18
- **Afecta a:** `params.yaml: ontology` (descripción de `pole_lv` y `pole_mv`),
  la anotación de todos los bloques
- **Origen:** al revisar las primeras predicciones de Sonata sobre
  `b_1465_43337`, el modelo encontraba el fuste de los postes pero no sus
  ménsulas ni sus retenidas. En `b_1464_43339` algunos postes se habían
  etiquetado con la retenida y otros sin ella.
- **Continúa a:** [0015](0015-la-mensula-es-parte-del-poste.md),
  [0023](0023-solo-postes-con-su-luminaria.md)

## Decisión

En la retenida tipo **violín** (un brazo rígido que sale unos 1,5 m de la punta
del poste y un cable que baja vertical hasta el anclaje en el piso):

| Parte | Clase |
|---|---|
| El **brazo rígido** sujeto al poste | **poste** (5 o 12), como cualquier ferretería acoplada (0015) |
| El **cable** que baja al piso, y el anclaje | **fondo** (0) |

La misma regla vale para la retenida común, que va en diagonal del poste al
piso: el cable es fondo.

## Por qué

**El cable se parece demasiado a un poste.** Es una línea vertical y delgada que
llega al piso, justo lo que el modelo aprende como fuste. Etiquetarlo como poste
le enseña que cualquier línea vertical fina es poste, y aumentan los falsos
positivos: bajadas de cable, tubos, postes de telecomunicaciones.

**Hay muy pocos ejemplos.** Un puñado de violines entre ~45 postes no basta para
que el modelo aprenda esa forma de forma fiable.

**No cambia lo que se mide.** El inventario de esta fase cuenta postes. El cable
no suma un poste ni cambia su tipo.

**Lo peor es mezclar las dos cosas.** Si el mismo tipo de punto es poste en un
árbol y fondo en otro, el modelo aprende ruido justo en esa zona. Por eso la
regla se aplica a todos los postes ya etiquetados, no solo a los nuevos.

## Qué queda

Si los proyectistas necesitan contar o medir retenidas, entrará como clase
propia (`retenida`, en espera), con brazo y cable juntos y con ejemplos
suficientes. Hasta entonces, nada de la retenida salvo el brazo se etiqueta
como poste.

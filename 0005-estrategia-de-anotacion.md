# 0005 — Los datos no traen etiquetas; la anotación es la ruta crítica

- **Estado:** aceptada
- **Fecha:** 2026-09-06
- **Afecta a:** `params.yaml: weak_labels.*`, `src/stages/s06_weak_labels.py`,
  `annotation/`
- **Gravedad:** bloqueante. Nada de lo que hay aguas abajo es real hasta que
  esto se resuelva.

## El hallazgo

La etapa 01 muestreó 20.3 M de puntos en 12 de los 61 archivos entregados y
encontró:

```
classification_counts: {"1": 100 %}
```

Todos los puntos llevan clasificación LAS 1 — *sin clasificar*. El conjunto
entregado de **421 M de puntos tiene cero etiquetas**.

Es el hallazgo **Q2** en `reports/raw_profile.json`, y es el hecho más
consecuente de todo el proyecto.

## Por qué cambia el plan

El planteamiento inicial dedicaba su esfuerzo algorítmico a elegir entre
RandLA-Net, MinkowskiEngine y transformers 3D. Las tres son supervisadas. Sin
etiquetas las tres son igual de inservibles, así que esa elección no puede ser el
cuello de botella — y tratarla como tal esconde el riesgo real.

Dimensionamiento aproximado del problema real: un anotador competente etiquetando
datos urbanos de cartografía móvil desde cero avanza del orden de una tesela por
hora una vez la escena se pone densa. Las 36 teselas materializadas en la fase 1
son ya cerca de una semana de trabajo de una persona, y 36 teselas son el
**0.5 %** del área entregada. Para un equipo de tres con un semestre por delante,
etiquetar desde cero no cierra.

## La decisión

No etiquetar desde cero. **Generar un borrador geométrico y luego corregirlo.**
Corregir un borrador es aproximadamente un orden de magnitud más rápido que
pintar desde nada, porque la tarea del anotador cambia de «selecciona todos los
puntos de esta clase» a «arregla donde la regla se equivocó».

`src/stages/s06_weak_labels.py` produce ese borrador a partir de los rasgos de la
etapa 05 usando reglas explícitas y auditables. Dos propiedades lo hacen seguro:

1. **Las reglas nunca se sobrescriben entre sí.** Se aplican de la más fiable a
   la menos (cables, luego postes, luego fachadas, luego el reparto del suelo) y
   una regla posterior no puede reclamar un punto que ya tomó una anterior.
2. **Lo no reclamado queda como `unclassified`.** Una etiqueta equivocada es peor
   que ninguna, porque el anotador no pensará en revisarla. Todo aquello sobre lo
   que las reglas no tienen confianza se deja para una persona.

Cada punto lleva además una `label_confidence`, para poder ordenar teselas por
cuánto dudaron las reglas y para que la etapa 07 pueda excluir de la pérdida los
puntos de baja confianza.

## Qué pueden y qué no pueden hacer las reglas

| Clase | Regla | Confianza |
|---|---|---|
| 6 power / 7 telecom | linealidad alta a 0.30 m + HAG ≥ 4 m + sección delgada | **alta** para «es un cable», **baja** para cuál de los dos |
| 5 poste | verticalidad ≥ 0.85 a 0.80 m + columna ≥ 3 m | media |
| 3 construcción | planaridad ≥ 0.60 + verticalidad ≥ 0.80 + HAG ≥ 1 m | media |
| 1 pista / 2 vereda | tipo suelo, repartido por una altura de sardinel | **baja** |
| 4 buzón | **ninguna — desactivada a propósito** | — |

Tres de ellas merecen explicación.

**El reparto power/telecom es la más débil de las reglas fuertes.** La separación
es un único umbral de altura, `weak_labels.wires.power_tier_min_hag_m: 7.0`,
sobre el supuesto de que el nivel eléctrico cuelga por encima del de telecom. Esa
es la convención habitual, y es *provisional*: no se ha contrastado contra postes
reales de este distrito. Es lo primero que el anotador debe verificar, y si la
convención no se cumple localmente, la regla debe sustituirse por una basada en
grosor de haz y altura de amarre al poste, no ajustando el 7.0.

**El reparto pista/vereda supone un plano de calzada local plano.** Fallará en
calles con bombeo, en rampas y en accesos vehiculares, y los autos estacionados
son lo bastante planos y bajos como para que algunos se etiqueten como pista.
Hay que esperar corregir esta clase más que ninguna otra.

**Los buzones no se intentan.** Una tapa es *coplanar con la superficie de la
pista*; no hay firma geométrica que encontrar. Separarla requiere evidencia de
intensidad o color (metal contra asfalto), y esa separabilidad todavía no se ha
medido. Emitir una conjetura aquí crearía falsos positivos silenciosos en una de
las dos clases destinadas a exportación CAD, lo cual es peor que no emitir nada.
`weak_labels.manhole.enabled` está en `false`, y la etapa lanza un error si
alguien lo pone en `true` sin escribir la regla.

## El ciclo del que esto forma parte

```
etiquetas débiles  ->  corrección humana en CloudCompare  ->  entrenar
        ^                                                        |
        |                                                        v
 corregir las predicciones  <-  predecir sobre teselas sin anotar
```

Tras la primera pasada de corrección el modelo se convierte en mejor etiquetador
que las reglas, y las reglas se retiran. Las teselas se priorizan para anotación
por incertidumbre del modelo, no por índice de tesela — eso es aprendizaje activo
convencional y es donde debe ir el presupuesto de anotación restante.

## Reglas duras que se derivan

- **Las etiquetas débiles nunca son un conjunto de test.** Una métrica calculada
  contra la salida de las reglas mide el acuerdo con las reglas, no con la
  realidad. `dataset.test` está deliberadamente vacío en `params.yaml` hasta que
  existan teselas corregidas por una persona.
- **`label_is_draft` viaja con cada fila** de la tabla de modelado, para que
  ningún consumidor aguas abajo pueda perder la pista de qué etiquetas ha visto
  un humano.
- **No ajustar las reglas contra métricas del modelo.** Existen para ahorrar
  tiempo de anotación, no para maximizar nada.

## Entrega práctica

La etapa 06 escribe `annotation/<escaneo>/t_<ix>_<iy>.laz` con el borrador en el
campo `classification` y el CRS estampado. Se abre en CloudCompare, se corrige y
se guarda con los mismos códigos. Conviene usar los colores de
`params.yaml: ontology` para que una clase se vea igual en CloudCompare, en el
visor de nivel 2 y en cualquier informe.

Empezar por las teselas cuyo `claimed_pct` en `reports/weak_labels.json` sea
**más alto**: son aquellas donde las reglas más aportaron y donde la corrección
rinde más por punto etiquetado.

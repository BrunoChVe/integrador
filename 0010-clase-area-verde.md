# 0010 — Novena clase: jardín o área verde junto a la calzada

- **Estado:** aceptada (reglas del borrador **provisionales**)
- **Fecha:** 2026-09-11
- **Afecta a:** `params.yaml: ontology`, `params.yaml: weak_labels.green_area`,
  `src/stages/s06_weak_labels.py`
- **Origen:** solicitud del equipo, para completar el contexto de superficie
  entre la calzada, la vereda y las fachadas.

## Decisión

Se añade la clase **`green_area`** (`jardin_area_verde`) con **id 8**. La
ontología pasa de ocho a nueve clases.

**Incluye** las superficies vegetales a nivel de suelo contiguas a la calzada:
jardines, bermas y separadores centrales con césped, maceteros y alcorques.

**No incluye las copas de los árboles.** La vegetación en altura sigue en
`unclassified`.

## Por qué el id 8 y no un hueco en medio

Los ids están incrustados en los checkpoints entrenados y en las teselas
anotadas, así que **nunca se renumeran**. Todavía no existe ninguno de los dos,
pero la regla se mantiene: añadir al final deja intactos los ids de las otras
ocho clases, y cualquier informe o figura anterior sigue siendo legible.

## Qué dicen los datos antes de escribir la regla

Medido sobre seis teselas densas (3.9 M de puntos) **antes** de fijar umbrales:

| Medición | Valor |
|---|---|
| Puntos a nivel de suelo (−0.3 a 0.8 m sobre el terreno) | 1 709 318 |
| De ellos, con tono verde saturado (70–170°, saturación y brillo ≥ 0.12) | **15 290 · 0.89 %** |
| Puntos verdes por encima de 2 m (copas) | 38 329 · 0.97 % del total |
| Tono dominante de los puntos saturados a nivel de suelo | **20–40°** (cálido) |

Dos consecuencias:

1. **La señal existe pero es débil.** En estas teselas —las más densas, que son
   calles con fachadas— el área verde es poca superficie. La clase será
   minoritaria, como los cables.
2. **El color tiene una dominante cálida.** La mayoría de los puntos saturados
   caen entre 20° y 40°, no en el gris neutro que cabría esperar de asfalto y
   concreto. Un césped seco o una colorización con esa dominante se desplaza
   hacia el amarillo y **escapa de una banda de tono fija**. Por eso la regla es
   provisional y no se le da más confianza de la que tiene.

## La regla del borrador

```yaml
weak_labels:
  green_area:
    enabled: true
    hag_m: [-0.30, 0.80]        # superficie o seto bajo, nunca copa
    hue_deg: [70, 170]          # los mismos umbrales con que se midió
    min_saturation: 0.12
    min_value: 0.12
    confidence: 0.45
```

**Orden de aplicación:** después de cables, postes y fachadas, y **antes** del
reparto pista/vereda. Si fuera después, esa regla —que reclama todo lo que está
a nivel de suelo y es aproximadamente plano— se quedaría con el césped como
pista o vereda, y la clase nueva no recibiría puntos.

**Confianza 0.45**, por encima del umbral de entrenamiento (0.35). Por debajo,
la clase desaparecería del conjunto de entrenamiento sin ningún error, que es
exactamente el defecto documentado en
[0008](0008-umbral-de-confianza.md).

## Debilidades conocidas

- **Césped seco o amarillento** queda fuera de la banda de tono. Es lo primero
  que hay que revisar al corregir.
- **Superficies verdes que no son vegetación:** autos, toldos y pintura.
- **Sombras:** desaturan el color y el césped sombreado se pierde.
- **La geometría no se usa todavía.** El césped es rugoso y la pista es lisa;
  la rugosidad local separaría mejor que el color, pero no se ha medido.

## Lo que queda abierto, y por qué importa

**Los árboles.** Dejarlos en `unclassified` es coherente con lo pedido («jardín
o área verde junto a la calzada»), pero la vegetación en altura junto a los
conductores es relevante para las distancias de seguridad. Si esa medición
entra en el alcance, conviene decidir pronto si los árboles merecen su propia
clase: añadirla después obliga a revisar todas las teselas ya anotadas.

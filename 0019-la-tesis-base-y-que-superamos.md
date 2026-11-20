# 0019 — La tesis base: qué tomamos y qué superamos

- **Estado:** aceptada
- **Fecha:** 2026-10-03
- **Afecta a:** `params.yaml: weak_labels.wires`
- **Origen:** una tesis de maestría de la UPC que usa la **misma fuente de
  datos** de años anteriores. Leerla entera cambió dos umbrales de
  `params.yaml` y dejó claro con qué hay que compararse de verdad.
- **Nota (2026-10-17):** el PDF estuvo en `docs/tesis_base/` y se sacó del
  repositorio. Es obra de terceros: se cita por su handle, no se redistribuye.
  Las páginas que se citan abajo son las del PDF del repositorio de la UPC.

## Contexto

Benites Dávila, Apaza Flores, Céspedes Cuadros y Ampuero Cutty; asesor Vargas
Cirilo; 6 de noviembre de 2024; handle
<http://hdl.handle.net/10757/682910>. 191 páginas. LiDAR móvil Quanergy M8 sobre
calles de Lima, LAS 1.2, ~10 M puntos y ~1 km por archivo: nuestro mismo sensor,
nuestra misma ciudad, años anteriores.

Es la referencia que esta etapa quiere superar, así que conviene dejar por
escrito qué se toma, qué no, y contra qué número se mide el capstone.

## Qué hacen

Dos clases reales: **suelo** y **cableado de media tensión**. Su tercera
«clase», *objeto cercano*, no es semántica: es cualquier conjunto de ≥10 puntos
no clasificados a menos de 3 m del conductor (textual, p. 109).

**No detectan postes** —lo declaran como limitación en p. 17— y la palabra
«luminaria» no aparece en las 191 páginas. Reseñan PointNet, PointNet++,
VoxelNet y RandLA-Net (pp. 24-32) pero **no entrenan ninguna red**; el motivo
declarado es la ausencia de datos etiquetados.

## Cómo etiquetaron: no etiquetaron

Textual (p. 89): *«no existe una fuente de datos etiquetados para la clase
cableado de media tensión»*. Lo que hicieron fue **calibrar umbrales a ojo**
visualizando 53 nubes de 8 distritos, ~530 M puntos (pp. 89 y 95). No mencionan
ninguna herramienta de anotación en todo el documento.

Su pipeline son seis capas de DBSCAN encadenadas (eps 1.8, 1.5, 2.5, 1.2, 20,
3), cada una con su tabla de umbrales, más RANSAC, más una regresión lineal
entrenada con las etiquetas que produjo su propia capa 4 sobre la misma escena.

## Sus métricas no son una barra seria

Reportan accuracy 85.31 %, precision 93.10 %, recall 89.40 %, F1 **91.22 %**
sobre 14 nubes (~126.3 M puntos) de las mismas 53 con que calibraron. Los
problemas son concretos:

| | Problema |
|---|---|
| 1 | La **unidad de conteo no se define en ninguna parte** del documento. No hay una frase que diga qué es un verdadero positivo. Por los valores —TP de 1 a 21 por nube de 1 km— parecen ser tramos verificados a ojo. |
| 2 | Los **verdaderos negativos valen 1 en doce de las catorce nubes** y 2 en una. Imposible en una nube de 10 M puntos, e infla el accuracy. |
| 3 | Las **sumas no cuadran**: los anexos dan 132 TP y 15 TN; el anexo 16 dice 135 y 16. |
| 4 | No hay IoU, ni mIoU, ni métrica por punto, ni matriz multiclase. |
| 5 | No hay holdout ni validación cruzada: se mide sobre las nubes de calibración. |

Queda escrito aquí: **superar su 91.22 % no es un objetivo significativo**, y
presentarlo como tal sería deshonesto. El aporte real del capstone es la primera
métrica bien definida sobre esta fuente de datos, apoyada en ground truth
propio.

## La barra de verdad es Guan et al. 2021

Que ellos mismos reseñan, en p. 59: PointNet sobre un dataset propio de **3 536
tramos de línea etiquetados a mano**, cinco clases (edificaciones, suelo,
vegetación, conductores, postes), split 75/25, **F1 > 0.97 en conductores y
> 0.93 en postes**.

Ése es el número con el que compararse. Y confirma algo útil: la tarea es
alcanzable con el método que ellos descartaron. El bloqueo era el dataset, no el
método.

## Dónde nos dan la razón

Sus falsos positivos en Barranco 1 son, textual (p. 133): *«puntos de otros
componentes de media tensión que no fueron detectados por el modelo, tales como
postes y subestaciones aéreas. La clasificación de estos objetos queda por hacer
para futuras mejoras»*.

Su principal fuente de error son justo las clases que
[0017](0017-alcance-reducido-postes-luminaria-y-red-mt.md) pone como activas.

## Qué tomamos, y ya está aplicado en `params.yaml`

**Separación entre fases MT, medida sobre esta misma fuente** (tabla 19, p. 102):

| Armado | Separación medida |
|---|---|
| Circuito simple, tres fases | 0.9-1.8 m |
| Doble circuito, seis conductores | 2.0-3.4 m |

`weak_labels.wires.mv_bundle.spacing_m` pasa de `[0.3, 1.5]` a **`[0.3, 3.4]`**.
El techo de 1.5 m excluía el doble circuito entero, que en esta red existe. Se
conserva el piso de 0.3 m —por debajo de su 0.9 m medido— porque el armado
compacto peruano lleva las fases más juntas, y porque `max_cluster_diameter_m`
(0.35 m) ya impide que un conductor grueso cuente como dos.

**Altura mínima de MT.** El CNE Suministro 2011 fija la MT **a partir de 5.5 m**
y hasta 7 m según zona (p. 86). Ellos prefiltran a `altura >= 7` y pierden en
silencio toda la MT baja, sin discutirlo en ninguna página. Nuestro
`mv_min_hag_m` era 9.0 —**aún más agresivo que su 7**—, así que heredábamos el
mismo fallo y peor. Baja a **7.5 m**: deja 2 m de margen sobre el mínimo
normativo, no se traga la BT, y el haz trifásico recupera lo que quede por
debajo.

**Umbrales normativos del CNE que confirman decisiones nuestras:**

| Umbral | Valor | Dónde pesa |
|---|---|---|
| Vano máximo MT | 70 m (p. 13) | justifica el bloque de 200 m de [0018](0018-el-bloque-de-anotacion-sustituye-a-la-tesela.md) |
| BT bajo MT | 1.2 m | separación entre niveles de conductor |
| Telecom | 0.6 m bajo BT, 1.8 m bajo MT | el par BT/telecom de 0013 |

## Qué no tomamos, y por qué

- **Su voxelización por `gps_time` de 0.25 s para clasificar suelo** (pp. 91-94)
  es la mejor idea de la tesis: el vóxel sigue la trayectoria del vehículo y
  absorbe la pendiente de la calle sin ajustar planos —histograma de Z por
  vóxel, límite inferior del bin modal como nivel de suelo, suelo si la altura
  relativa es ≤ 0.4—. Queda **anotada como pendiente y no implementada**.
  Nuestro `ground.cloth_grid` ajusta una rejilla de 1 m sobre el bloque entero,
  y a 200 m el área es 25 veces la de la tesela de 40 m, así que el riesgo de
  que la pendiente arrastre el suelo es real y hay que medirlo. Es el candidato
  número uno si la altura sobre el suelo sale mal en el bloque.
- **`normal_z` como separador poste/conductor** (p. 90: poste tiende a 0,
  conductor a 1, con menos del 6 % de excepciones). Ya lo tenemos equivalente y
  mejor en la `verticality` del PCA local multiescala, que no depende de un radio
  único de 3 m — demasiado grueso para un poste de 0.2-0.3 m de diámetro.
- **Su filtro de color e intensidad** (`red >= 50`, `80 <= intensity <= 220`),
  que elimina más del 95 % de los puntos. Calibrado para otro año, otra cámara y
  otro sensor. Reutilizar esos valores sin recalibrar sería copiar una constante
  ajena, que es justo lo que `params.yaml` existe para evitar.
- **Toda su capa de zonas de riesgo** (Convex Hull por tramos de 4 vóxeles,
  ampliación de prisma de 5 m, distancia máxima 3 m) es post-procesamiento aguas
  abajo de la segmentación. El cálculo de distancias mínimas de seguridad no es
  lo que resuelve esta etapa.
- **Su arquitectura de seis DBSCAN encadenados.** Ninguno de los seis valores de
  eps tiene justificación más allá de inspección visual. Vale como catálogo de
  rangos, no como arquitectura.

## Modos de fallo que ellos declaran y que un modelo supervisado no hereda

Útil para el informe final:

- El **doble circuito de seis líneas** les da más error, porque su método asume
  paralelismo estricto.
- **Pierden los tramos donde el tendido pasa de disposición vertical a
  horizontal**, porque la regresión lineal los descarta por error excesivo.
- Su modelo **exige que exista al menos un tramo de cableado libre de ruido por
  vano** (p. 95). En red urbana con telecom y arbolado esa suposición se cae a
  menudo.

Los tres son limitaciones de un pipeline de reglas geométricas, no de la fuente
de datos. Es el argumento de fondo para gastar el esfuerzo del capstone en
ground truth y no en más umbrales.

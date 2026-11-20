# Selección de red para segmentación de nubes urbanas a gran escala

**Lo primero, sin rodeos.** La arquitectura no es el problema de este proyecto.
Los datos están 100 % sin etiquetar, y todos los candidatos de abajo —RandLA-Net,
MinkowskiEngine, un Point Transformer— necesitan etiquetas. Elegir entre ellos
antes de que exista una sola tesela anotada es optimizar la variable equivocada.

Lo que sigue merece decidirse ahora igualmente, porque dos de las opciones del
planteamiento inicial **no se pueden instalar en la máquina que tiene este
equipo**, y descubrirlo después de anotar habría costado semanas.

## La restricción de hardware, medida

| | |
|---|---|
| GPU | NVIDIA RTX 4060 Laptop, **8 GB de VRAM**, driver 555.97 |
| CPU | Intel i7-13650HX |
| RAM | **15.6 GB** |
| Sistema | **Windows 11** |
| Python | 3.12, **solo pip** (sin conda) |

Tres de ellas son vinculantes: los 8 GB de VRAM, Windows, y solo pip.

## Los candidatos

### MinkowskiEngine — descartado

Aparece en el planteamiento inicial. Es una buena biblioteca y **no es
realistamente instalable aquí**. Compila extensiones CUDA contra un par
PyTorch/CUDA concreto, su compilación nunca ha tenido soporte de Windows de
primera clase, y el mantenimiento aguas arriba es escaso desde 2022. Ponerlo a
funcionar en Windows implica cadena de herramientas de Visual Studio, cabeceras
parcheadas y versiones fijadas, y se rompe en la siguiente actualización de
PyTorch.

Si lo que se busca es convolución dispersa —y encaja bien—, hay una biblioteca
que se instala desde pip en Windows y da la misma familia de modelos.

### spconv (`spconv-cu120`) + U-Net dispersa estilo MinkUNet — **recomendado como modelo principal**

- `pip install spconv-cu120` ofrece rueda precompilada para Windows. Sin
  compilador.
- Arquitectónicamente equivalente a MinkowskiNet: convoluciones dispersas
  submanifold sobre un hash de vóxeles, codificador/decodificador U-Net con
  conexiones de salto.
- El tamaño de vóxel ya está fijado en **5 cm** por la decisión de limpieza
  (`docs/decisiones/0004-el-sor-destruye-los-cables.md`), que es además lo que
  quiere una U-Net dispersa.
- 8 GB bastan para una tesela de 40 m a 5 cm con `amp: true` (fp16) y
  `batch_tiles: 2`. Esto se dimensionó a propósito: `tiling.tesela_m` de
  `params.yaml` se eligió contra este presupuesto de VRAM, no al revés.
  El vóxel de 5 cm ya no está en `params.yaml`: vivía en `downsample.model_m`,
  que se fue con la etapa de limpieza
  ([0017](../decisions/0017-alcance-reducido-postes-luminaria-y-red-mt.md)).
  Hay que volver a declararlo al escribir el entrenamiento, que es también
  donde se decidirá si el modelo voxeliza o come la nube a resolución completa:
  se anota sobre el bloque entero, sin voxelizar, así que la decisión ya no está
  tomada aguas arriba.

### RandLA-Net — **recomendado como línea base ligera**

- PyTorch puro, sin operador CUDA propio, se instala en cualquier sitio.
- Diseñado exactamente para esta entrada: escenas exteriores grandes, millones de
  puntos, muestreo aleatorio con agregación local de rasgos.
- Más débil que una U-Net dispersa en estructuras finas, porque el submuestreo
  aleatorio es poco amable con un conductor de un vóxel de ancho. Útil como
  comprobación de cordura y como alternativa si spconv se rompe con una
  actualización de driver.

### Point Transformer V3 / transformers 3D — aplazado

Hoy son los mejores resultados publicados en benchmarks exteriores. Dos problemas
prácticos aquí: la implementación de referencia se apoya en núcleos de
Flash-Attention orientados a Linux, y la atención sobre una tesela completa
consume memoria de una forma que 8 GB no perdonan. Reconsiderarlo si el equipo
consigue una máquina Linux o tiempo de GPU en la nube. No es una opción de
fase 1.

### La línea base que nadie planifica y todo el mundo necesita: árboles con boosting

`model.baseline` en `params.yaml` es LightGBM sobre la tabla de rasgos por punto
que la etapa 07 ya produce. No es un juguete:

- Entrena en **minutos sobre CPU**, así que existe antes que el pipeline de GPU.
- Con `height_above_ground` más los rasgos de autovalores multiescala, las clases
  definidas geométricamente (pista, fachada, poste, cable) son casi linealmente
  separables. Un ensamble de árboles llega bastante lejos con ellas.
- Da un **piso honesto**. Un modelo profundo que no lo supere no está
  funcionando, y sin la línea base ese fallo es invisible: parece simplemente que
  «la mIoU es la que es».
- Es interpretable: la importancia de rasgos dice directamente qué descriptores
  están justificando su coste, lo que realimenta `features.radii_m`.

**Orden de trabajo: primero la línea base, después la U-Net dispersa, el
transformer quizá nunca.**

## Por qué el tamaño de vóxel es una decisión de segmentación, no un ajuste de rendimiento

Un conductor de baja tensión mide 1-2 cm de sección. Con un vóxel de 10 cm, dos
hilos de telecom separados 8 cm se funden en un solo vóxel ocupado, y ninguna red
aguas abajo puede separar las clases 6 y 7 — la etiqueta se destruye antes de que
empiece el entrenamiento. A 5 cm siguen siendo distintos. Por eso
`downsample.model_m` está en `params.yaml` junto a la ontología y no en el bloque
del modelo: acota lo que es aprendible.

## De dónde salen realmente los centímetros

El planteamiento inicial pide medición milimétrica de distancias de seguridad.
Eso no es alcanzable con este sensor, y el plan no debería prometerlo.

El escáner es un **Velodyne VLP-16** —confirmado por los nombres de archivo
(`Puck*_colorized.laz`) y por `point_source_id` recorriendo 0-15, los dieciséis
índices de láser—. Su exactitud en rango ronda los **±3 cm (1 sigma)** antes de
sumar error de trayectoria y de registro. Ningún postprocesado recupera
información que el sensor nunca capturó.

Lo que **sí** es alcanzable, y para lo que está construido el pipeline:

1. Segmentar sobre la nube de vóxeles de 5 cm.
2. Transferir las etiquetas de vuelta a resolución completa por `voxel_inverse` —
   una consulta de índice exacta, sin interpolación ni búsqueda de vecino más
   cercano.
3. Ajustar una **catenaria analítica** a cada vano de conductor sobre los puntos
   crudos. Promediar cientos de medidas a lo largo de un vano atenúa la
   componente *aleatoria* del error; la curva ajustada queda mucho mejor
   localizada que cualquier punto individual.
4. Medir la distancia desde la curva ajustada hasta la superficie de terreno
   ajustada y hasta los planos de fachada ajustados — modelo contra modelo, nunca
   punto contra punto.

`postprocess.clearances.target_tolerance_m` está en **0.05 m** y se le pide al
pipeline que reporte su incertidumbre. Ese es un número defendible para poner
delante de un cliente. «Milimétrico» no lo es.

## Plan de entrenamiento, cuando existan etiquetas

| Paso | Qué | Por qué |
|---|---|---|
| 1 | LightGBM sobre la tabla de entrenamiento | métrica de piso, en una tarde |
| 2 | U-Net dispersa, 5 cm, fp16, 2 teselas por lote | el modelo real |
| 3 | `cross_entropy + lovasz` | Lovász optimiza IoU directamente, lo que importa cuando las clases 6/7 son <1 % de los puntos |
| 4 | pesos de clase `inverse_sqrt_frequency` | ya los calcula la etapa 07 sobre la partición de train |
| 5 | aprendizaje activo | predecir sobre teselas sin anotar y anotar donde el modelo esté menos seguro |

Reportar **IoU por clase, siempre**. La IoU media sobre nueve clases está dominada
por pista y fachada, que son fáciles y numerosas. Al negocio le importan las
clases 6 y 7, que son raras; `model.metrics.report_classes: [6, 7]` lo deja
explícito.

## Lo que no se puede saltar

Los puntos de buffer (`is_core == False`) existen para que los rasgos de vecindad
tengan contexto en los bordes de tesela. Deben excluirse de la función de pérdida
y de toda métrica. Incluirlos cuenta dos veces puntos que aparecen en dos teselas
e infla el resultado reportado.

# 0021 — La inferencia no depende del tamaño de la nube

- **Estado:** aceptada como **requisito**; la etapa que lo implementa no está escrita
- **Fecha:** 2026-10-03
- **Afecta a:** la futura etapa de inferencia, `docs/architecture/seleccion-de-red.md`,
  `params.yaml: tiling`
- **Origen:** requisito del equipo. El modelo entrenado tiene que poder correr
  sobre cualquier nube que llegue, sea de 40×40 m, de 60×60 m o de un kilómetro
  de calle, sin reempaquetarla a un tamaño concreto.

## Decisión

**El tamaño de la nube de entrada no es un parámetro del modelo.** La tesela de
`tiling.tesela_m` (40 m) es una decisión de **lote de entrenamiento** —lo que
cabe en 8 GB de VRAM a 5 cm— y no una propiedad de los datos ni del modelo.

Se registra ahora, antes de escribir el entrenamiento, porque es una decisión
que **se puede perder por accidente**: hay arquitecturas que la violan y es más
fácil descartarlas al elegir que al reentrenar.

## Qué prohíbe, y qué permite

**Prohibido:** cualquier arquitectura cuya salida dependa de la extensión de la
entrada. El caso típico es una rejilla de vóxeles de tamaño fijo aplanada hacia
una capa densa: funciona, acierta, y solo acepta nubes del tamaño exacto con el
que se entrenó. Si aparece una opción así en la comparativa, queda descartada
por este registro y no por su métrica.

**Permitido:** predicción **punto a punto**, donde cada punto recibe su clase a
partir de su vecindario y no de un marco global. Las tres candidatas de
`docs/architecture/seleccion-de-red.md` lo cumplen:

| | cumple | por qué |
|---|---|---|
| U-Net dispersa (spconv) | sí | convolución submanifold sobre un hash de vóxeles; no hay extensión fija |
| RandLA-Net | sí | muestreo aleatorio con agregación local, por punto |
| LightGBM sobre rasgos por punto | sí | una fila por punto, el tamaño de la nube es el número de filas |

## Cómo corre entonces sobre una nube cualquiera

1. **Cortar** con la misma rejilla determinista, anclada a la UTM absoluta. Una
   nube de 40 m cae en un bloque; una de un kilómetro, en varios.
2. **Predecir con el anillo de contexto puesto**, y conservar solo el núcleo de
   cada celda. Esto no es un detalle: un punto en el borde predicho sin sus
   vecinos sale mal, y el error se ve como **costuras rectas a lo largo de la
   rejilla**, que es la firma inconfundible de haberse saltado este paso. La
   maquinaria ya existe —los bloques guardan `buffer_m` de anillo y el núcleo se
   recalcula del id— y la inferencia tiene que usarla.
3. **Pegar** los núcleos. Como no se solapan por construcción, no hay que votar
   ni promediar nada.
4. Escribir un `.laz` con `classification` rellenado, que se abre en
   CloudCompare igual que un bloque de anotación. La prueba visual queda idéntica
   al flujo que el equipo ya conoce.

## Lo que sí tiene que coincidir con el entrenamiento

Y es donde está el riesgo real, no en el tamaño:

- **La densidad.** Medida sobre las dos entregas: **5 a 3 844 pts/m²** entre
  archivos. Un modelo entrenado en calle densa y aplicado a una pasada dispersa
  se degrada, y ninguna cantidad de cuidado con el tamaño lo arregla. Es el
  primer problema a atacar al entrenar, no este.
- **Los canales de entrada.** Si el modelo acaba usando rasgos calculados a
  mano, la inferencia tiene que calcular los **idénticos**, con los mismos
  radios y el mismo orden. Eso es una superficie de error grande y silenciosa:
  un radio distinto no da un error, da una métrica peor.
  Favorece a un modelo que coma `xyz + RGB` directo. Al borrar las etapas de
  rasgos ([0020](0020-tres-etapas-y-sin-borrador.md)) el repositorio quedó, por
  accidente, en la posición cómoda para esto.
- **El tamaño del vóxel**, si el modelo voxeliza. Ya no está en `params.yaml`
  —vivía en `downsample.model_m`— y hay que volver a declararlo con el
  entrenamiento, en un sitio que la inferencia también lea.

## Sin resolver

- **Cómo normalizar la densidad** entre entregas. Es la pregunta abierta más
  importante del entrenamiento y no se decide aquí.
- Un mínimo práctico de tamaño, que es físico y no de rejilla: si la nube de
  prueba parte un poste por la mitad, ningún modelo acierta. Para una prueba
  honesta hacen falta **al menos ~100 m de calle**, de forma que entre un vano
  de MT completo y las puntas de los postes. No es una restricción del modelo,
  es que no hay objeto que reconocer.
- Si cambiar `tesela_m` obliga a reentrenar: sí, cambia el contexto que ve el
  modelo. Lo que **no** obliga es a reanotar, porque la verdad de campo se
  guarda por coordenada y es independiente de las dos rejillas
  ([0018](0018-el-bloque-de-anotacion-sustituye-a-la-tesela.md)).

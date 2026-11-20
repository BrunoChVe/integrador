# 0026 — La partición de entrenamiento la dicen las carpetas

- **Estado:** aceptada
- **Fecha:** 2026-10-31
- **Afecta a:** `datos/crudo/etiquetado/`, `etapa_4_5_modelado_evaluacion/codigo/postes/postes_datos.py`
- **Convive con:** [0024](0024-particion-por-superceldas.md), que sigue partiendo todos los bloques.

## Contexto

La partición por superceldas de 0024 deja los 12 bloques etiquetados en train y valid, sin
ninguno en test. Entrenar con ella no permitiría medir nada en bloques no vistos. Además, las
etiquetas llegan de a un bloque: una persona termina los recortes y decide a qué conjunto va.

## Decisión

Cada bloque etiquetado se guarda con su nube y sus recortes `_BT` y `_MT` en
`datos/crudo/etiquetado/<escaneo>/train/` o `test/`, y esa carpeta decide el conjunto.
Validación se aparta de train por nombre (`VAL_DE_TRAIN`).

## Consecuencias

- Los bloques vecinos pueden caer en conjuntos distintos, y por el anillo de contexto un poste
  puede aparecer en ambos. Medido: 3 postes. Se excluyen de la métrica de validación y de test
  (`marcar_compartidos`). Train no se toca.
- Es más débil que 0024: dos bloques contiguos pueden estar en train y test aunque no compartan
  postes, y la métrica puede salir optimista. Se acepta mientras haya pocas etiquetas.
- Cuando haya bloques etiquetados en todas las superceldas, conviene volver a 0024 o a validación
  cruzada por bloques.

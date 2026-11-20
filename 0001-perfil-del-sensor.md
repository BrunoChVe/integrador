# 0001 — Qué entregó realmente el sensor

- **Estado:** aceptada
- **Fecha:** 2026-09-06
- **Fuente:** `reports/raw_profile.json`, generado por `src/stages/s01_catalog.py`
  sobre los 61 archivos y una muestra de 20.3 M de puntos.

## Perfil medido

| Propiedad | Valor | Qué obliga |
|---|---|---|
| Puntos | **421 156 950** | Nada se puede procesar por escaneo; el pipeline es por teselas |
| Archivos | 61 `.laz`, 3.16 GB comprimidos | |
| Formato | LAS 1.2, point format 3 | xyz + intensidad + gps_time + RGB |
| Escala | 0.001 m | Resolución de *almacenamiento* milimétrica — no exactitud |
| CRS | **ausente en todos los archivos** | Hay que estamparlo al exportar (hallazgo Q1) |
| Clasificación | **1 en todos los puntos** | 100 % sin etiquetar (hallazgo Q2, ver 0005) |
| Retornos | **retorno único solamente** | Descarta el filtrado de suelo por último retorno (Q3) |
| RGB | Campos de 16 bits, valores 0-255, 0 % negros | Una normalización ingenua a 16 bits ennegrecería todo (Q4) |
| Intensidad | 0-255 | |
| `point_source_id` | 0-15 | Los dieciséis láseres del VLP-16 — utilizable como rasgo |
| Densidad | 44-1152 pts/m² entre archivos | Un rasgo de radio fijo no es comparable entre teselas (Q5) |

## El sensor

Los nombres de archivo (`Puck1_002_colorized.laz`) y el `point_source_id`
recorriendo 0-15 identifican un **Velodyne VLP-16 «Puck»** sobre plataforma de
cartografía móvil.

Este es el hecho que acota todo el entregable. La exactitud en rango del VLP-16
ronda **±3 cm (1 sigma)**, antes de sumar error de trayectoria y de registro. El
objetivo de medición *milimétrica* del planteamiento inicial no es alcanzable
con estos datos, y el presupuesto de exactitud en `params.yaml`
(`postprocess.clearances.target_tolerance_m: 0.05`) refleja el sensor y no la
aspiración. En `docs/architecture/seleccion-de-red.md` está explicado cómo se
recuperan los centímetros: ajustando curvas analíticas sobre cientos de puntos,
nunca midiendo punto a punto.

Conviene señalar la trampa que esconde el `scale` del LAS: 0.001 m es la
*cuantización del almacenamiento*. No dice nada sobre la exactitud, y leerlo
como «datos milimétricos» es exactamente cómo un proyecto acaba prometiendo
milímetros.

## Datum vertical

Valores de `Z` entre 370 y 463 m sobre Lima son demasiado altos para ser alturas
ortométricas. Se tratan como elipsoidales y quedan marcados como `unverified` en
`params.yaml` hasta que el proveedor lo confirme. Aguas abajo solo se usan
alturas *relativas*, así que ninguna distancia de seguridad depende de
resolverlo — pero nada debe exportarse como cota absoluta hasta que se resuelva.

## Qué es realmente el color

Las nubes entregadas son `*_colorized`: la proyección fotogramétrica ya está
aplicada y el 0 % de los puntos muestreados son negros. Los 16.8 GB de JPEG
Ladybug son por tanto **entradas de un paso que ya se ejecutó**, no entradas de
este pipeline. Ninguna etapa lee un JPEG.

Esa medición es la que justifica sacarlos del repositorio por completo
([0009](0009-solo-nubes-laz.md)): 33.6 GB liberados sin perder ni un dato que
el pipeline consuma.

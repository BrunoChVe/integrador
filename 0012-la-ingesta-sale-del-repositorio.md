# 0012 — La ingesta sale del repositorio

- **Estado:** aceptada
- **Fecha:** 2026-09-11
- **Afecta a:** `ingest/` (retirada), `.download_state/` (retirada), `.gitignore`,
  README, guías
- **Relacionada con:** [0002](0002-almacenamiento-y-remotos.md) y
  [0009](0009-solo-nubes-laz.md), que documentan decisiones tomadas cuando el
  descargador aún vivía aquí

## Decisión

Los scripts de descarga desde OneDrive/SharePoint (`od_download.py`,
`od_extract.py`, su README y el archivo del enlace) **salen del repositorio**.
Con ellos sale `.download_state/` (manifiesto, estado de reanudación y logs).

Su nuevo sitio, fuera del proyecto:

```
D:\MAESTRIA DATA SCIENCE\semestre5\proyecto_integrador\ingesta_onedrive\
├── scripts\           od_download.py, od_extract.py, README_DESCARGA.md
└── .download_state\   manifiesto, estado y logs
```

El repositorio empieza donde empieza el trabajo de datos: **los `.laz` ya
puestos en `data/raw/<grupo>/<escaneo>/LiDAR/`**.

## Por qué

1. **El alcance del proyecto es el desarrollo, no la obtención de los datos.**
   Conseguir el archivo es un trámite logístico con la empresa; lo que se
   evalúa y se reproduce es el pipeline que lo convierte en una nube
   segmentada. Mezclarlos hacía parecer que descargar era una etapa del método.
2. **Reduce la superficie de exposición.** El descargador necesita el enlace
   compartido, el tenant y, en algunos modos, cookies o un token. Nada de eso
   tiene por qué estar cerca de un repositorio que se comparte con terceros.
   El enlace ya se retiró del historial el mismo día.
3. **El pipeline nunca dependió de la ingesta.** La etapa 1 leía el manifiesto
   del descargador para registrar hashes; desde [0011](0011-eda-reproducible.md)
   calcula MD5 sobre los archivos, así que ya no había ninguna dependencia real.
   Esta decisión solo retira lo que sobraba.

## Consecuencias

- **Cuando lleguen datos nuevos** (se esperan 4 o 5 grupos más): quien los baje
  los deja en `data/raw/<grupo>/<escaneo>/LiDAR/`, y el repositorio sigue como
  siempre:

  ```bash
  dvc unprotect data/raw/<grupo>/*/LiDAR    # la caché usa enlaces duros
  dvc add       data/raw/<grupo>/*/LiDAR
  git commit -m "data: qué llegó y por qué importa"
  dvc repro                                  # el pipeline se pone al día
  ```

  Y añadir el escaneo a `select.scans` en `params.yaml` y a las dependencias de
  la etapa `eda` en `dvc.yaml`.
- **La procedencia sigue siendo auditable** sin el descargador:
  `reports/raw_inventory.csv` trae el MD5 de cada archivo, y es una salida
  declarada de la etapa `catalog`.
- **Lo que dicen 0002 y 0009 sigue siendo cierto**, pero las rutas
  `ingest/od_download.py` que citan hoy apuntan a la carpeta externa.
- Si alguna vez hiciera falta recuperar la fotogrametría (0009), el
  procedimiento es el mismo, ejecutado desde la carpeta externa.

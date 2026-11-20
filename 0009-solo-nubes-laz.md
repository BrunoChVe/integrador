# 0009 — El proyecto usa solo las nubes .laz; la fotogrametría sale del repositorio

- **Estado:** aceptada
- **Fecha:** 2026-09-10
- **Afecta a:** `data/raw/`, el descargador, `.dvc/cache`, el remoto local
- **Nota (2026-09-11):** los scripts de ingesta ya no viven en el repositorio
  ([0012](0012-la-ingesta-sale-del-repositorio.md)). Donde aquí se lea
  `ingest/od_download.py`, hoy es `od_download.py` en la carpeta externa.
- **Sustituye la reserva planteada en:** [0002](0002-almacenamiento-y-remotos.md),
  que proponía conservar los JPEG registrados pero sin subirlos a Drive

## Decisión

Las 18 095 imágenes Ladybug (16.8 GB) se eliminan del workspace, del control de
versiones y del remoto. El proyecto trabaja **únicamente con los 61 archivos
`.laz`** (3.16 GB).

## Por qué se puede

Las nubes entregadas son `*_colorized`: **la proyección fotogramétrica ya está
aplicada**. La etapa 01 lo midió sobre 20.3 M de puntos reales — 0 % de puntos
negros, color en el rango 0-255 en los tres canales. El color ya está incorporado
a cada punto.

Las imágenes son, por tanto, **entradas de un paso que ya se ejecutó**. Ninguna
etapa del pipeline abre un JPEG; se puede comprobar:

```bash
grep -rn "\.jpg\|Camera" src/    # no devuelve nada
```

## Por qué conviene

| | Antes | Después |
|---|---|---|
| `data/raw` | 20.0 GB · 18 159 archivos | **3.2 GB · 64 archivos** |
| Caché DVC | 30.22 GB · 18 520 objetos | **13.42 GB · 410 objetos** |
| Remoto local (D:) | 30.2 GB | **13.42 GB** |
| Libre en E: | 18.4 GB | **35.2 GB** |
| Libre en D: | 32.3 GB | **49.1 GB** |

**33.6 GB liberados** entre las dos particiones. En un equipo cuyas tres
particiones son del mismo NVMe de 477 GB, eso deja de ser una cifra cosmética:
es la diferencia entre poder procesar más teselas o no.

El segundo beneficio es la migración a Drive. Como quedó registrado en 0002, DVC
almacena bloques direccionados por contenido, así que las carpetas `Camera/`
habrían supuesto **18 095 subidas individuales** a Drive: lento por archivo,
sujeto a límite de tasa, y con alta probabilidad de fallar a media transferencia.
Ahora la subida completa son 410 objetos.

## Qué se conserva

- Los **61 `.laz`**, que es lo único que consume el pipeline.
- Los tres **`LadybugEvents_*.txt`** (1.5 MB en total). Son el registro de
  trayectoria de la cámara: identificador, marca de tiempo, posición este/norte/
  altura y actitud por cada disparo. No son imágenes, y describen la geometría de
  adquisición — potencialmente útiles para derivar el rango desde la trayectoria
  o la geometría de barrido. Ocupan nada y se quedan.

## Qué se pierde, exactamente

**No se pierden datos.** Las imágenes siguen en el OneDrive de origen, y
`ingest/od_download.py` sabe traerlas de vuelta y verificarlas contra el
`quickXorHash` que publica el servicio — una garantía más fuerte que «alguien las
subió a un remoto una vez».

```bash
# recuperarlas, si alguna vez hicieran falta
python ingest/od_download.py --exclude          # sin patrones = descargarlo todo
```

Lo que **sí** se pierde es la posibilidad de `dvc checkout` en la etiqueta
`raw-v1`. Esa etiqueta apunta a un commit donde existían los punteros
`Camera.dvc`, y los bloques correspondientes ya no están ni en la caché ni en el
remoto: recuperar ese estado exige volver a descargar del origen. Es una
consecuencia buscada —«quitarlo del control de versiones» significa esto— pero
conviene que esté escrita y no que alguien la descubra en un `checkout`.

## Lo que impide que vuelvan solas

El descargador **re-enumera el origen en cada ejecución**, que es lo que le
permite detectar datos nuevos. Sin más, borrar los JPEG habría durado exactamente
hasta el siguiente `od_download.py`.

Por eso el script tiene ahora una lista de exclusión, con la fotogrametría
excluida por defecto:

```python
DEFAULT_EXCLUDE = ["*/Camera/*"]
```

Son globs sobre la ruta relativa. El manifiesto registra qué patrones se
aplicaron y cuántos archivos y bytes descartaron, así que la exclusión queda
auditada igual que cualquier otra decisión.

Comprobado contra el manifiesto real antes de borrar nada: de 18 164 archivos,
quedan 69 (3.2 GB) y se excluyen 18 095 (16.8 GB). **Cero JPEG se cuelan y cero
`.laz` se pierden.**

## Cómo revertir

```bash
python ingest/od_download.py --exclude              # vuelve a bajar todo
dvc add data/raw/Grupo03_crudo_2025/*/Camera
git commit -m "data: se recupera la fotogrametria por <motivo>"
```

El motivo tendría que ser real: re-colorizar con otro criterio, o fusionar 2D-3D
para atacar la clase `manhole`, que es la única de la ontología donde el color y
la intensidad son la vía de separación (ver
[0005](0005-estrategia-de-anotacion.md)). Si se llega ahí, conviene empaquetar
cada carpeta `Camera/` en un solo archivo antes de registrarla: 3 objetos en el
remoto en lugar de 18 095.

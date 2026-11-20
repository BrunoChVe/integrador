# 0002 — Almacenamiento, caché de DVC y el camino a Drive

- **Estado:** aceptada
- **Fecha:** 2026-09-06
- **Afecta a:** `.dvc/config`, los nueve punteros `*.dvc` bajo `data/raw/`
- **Responde a:** «¿hace falta mover la carpeta `data/` a
  `D:\MAESTRIA DATA SCIENCE\semestre5\proyecto_integrador\dvc`?»
- **Parcialmente superada por:** [0009](0009-solo-nubes-laz.md). La reserva de
  «registrar los JPEG pero no subirlos a Drive» quedó obsoleta: se eliminaron
  del repositorio por completo. Todo lo relativo a la caché de enlaces duros,
  al remoto local y a la migración a Drive sigue vigente.
- **Nota (2026-09-11):** el remoto del equipo es hoy **Cloudflare R2**, no Google
  Drive, y los scripts de ingesta salieron del repositorio
  ([0012](0012-la-ingesta-sale-del-repositorio.md)): donde aquí se lea
  `ingest/od_download.py`, hoy es `od_download.py` en la carpeta externa.

## Respuesta corta

**No. No hay que mover `data/`.** No hay que mover nada. La carpeta `dvc/` en D:
aloja el **remoto**, no el workspace. Mover ahí los 20 GB de datos crudos
crearía una segunda copia que DVC tendría que copiar otra vez, y el disco no da
para eso.

## La medición que lo decide

`C:`, `D:` y `E:` son **tres particiones de un único NVMe de 477 GB**, no tres
discos:

| Partición | Libre | Función |
|---|---|---|
| C: | 16.1 GB | sistema |
| D: | 52.0 GB | remoto local de DVC |
| E: | 28.6 GB | workspace + datos crudos (los 20.0 GB ya están aquí) |

Dos consecuencias que el plan original no contemplaba:

1. **Un remoto local en D: no es una copia de seguridad.** Sobrevive a un
   borrado accidental, no a un fallo de disco — el mismo NVMe aloja ambas
   copias. Es una zona de preparación para la migración a Drive y una forma de
   probar `dvc pull`, nada más. Hasta que Drive esté activo, la fuente de verdad
   real es OneDrive.
2. **La caché por defecto de DVC no habría cabido.** Con `cache.type = copy`,
   `dvc add` escribe una segunda copia de cada archivo en `.dvc/cache`: 20 GB de
   workspace más 20 GB de caché contra 28.6 GB libres en E:. Habría fallado a
   medio camino.

## Qué se configuró en su lugar

```ini
[cache]
    type = "hardlink,symlink"
```

Los enlaces duros exigen que la caché y el workspace estén en el **mismo
volumen**, y lo están (ambos en E:). El archivo en `data/raw` y el de
`.dvc/cache` pasan a ser dos nombres para el mismo conjunto de bloques.

Verificado, no supuesto: E: tenía 28.6 GB libres antes del `dvc add` y 28.6 GB
después de registrar los 20 GB. Cero duplicación.

**El coste de los enlaces duros:** DVC deja las copias del workspace en solo
lectura, porque editarlas corrompería la caché en silencio. Es el
comportamiento que se quiere de todas formas: **los datos crudos son de solo
lectura**. Para añadir un escaneo recién descargado:

```bash
dvc unprotect data/raw/Grupo03_crudo_2025/AVP01MT2611202501/LiDAR
python ingest/od_download.py          # baja solo lo nuevo
dvc add   data/raw/Grupo03_crudo_2025/AVP01MT2611202501/LiDAR
git commit -m "data: qué llegó y por qué importa"
```

## Nueve punteros, no uno

`dvc add data/raw` habría producido un solo puntero. En su lugar, cada escaneo
se registra tres veces — `LiDAR/`, `Camera/` y la trayectoria `.txt`:

```
data/raw/Grupo03_crudo_2025/AVP01MT.../LiDAR.dvc           3.16 GB en total,     61 archivos
data/raw/Grupo03_crudo_2025/AVP01MT.../Camera.dvc         16.8  GB en total, 18 095 archivos
data/raw/Grupo03_crudo_2025/AVP01MT.../Ladybug....txt.dvc   1.5 MB en total,      3 archivos
```

Así el espejo de OneDrive queda idéntico byte a byte —lo que mantiene
`ingest/od_download.py` idempotente— y a la vez se pueden hacer **subidas
selectivas**. Eso importa por el problema de Drive que viene ahora.

## El problema de Google Drive, y es real

Las guías de referencia sobre remotos de DVC califican Drive de
**«desaconsejable»** y dan cuatro razones. Dos afectan directamente a este
proyecto:

1. **La autorización caduca cada 7 días** mientras la aplicación OAuth esté en
   estado de prueba con público externo. Quien reproduzca el trabajo una semana
   después obtiene un error de autenticación. *La salida:* la documentación
   señala que **con cuenta institucional y público interno no hay caducidad**.
   Como el 1 TB es institucional, el cliente OAuth **debe crearse dentro del
   proyecto Google Cloud de la institución con la audiencia en Interna**.
   Crearlo bajo una cuenta `@gmail.com` personal reintroduce la caducidad de 7
   días y el historial deja de ser reproducible.
2. **Cada objeto es un archivo de Drive independiente.** DVC almacena bloques
   direccionados por contenido, así que las carpetas `Camera/` se convierten en
   **18 095 subidas individuales**. Drive es lento por archivo y limita la tasa;
   son horas de transferencia que pueden fallar a la mitad.

### Decisión que se deriva

- **Subir el LiDAR a Drive. No subir Camera.** Los 3.16 GB / 61 archivos de
  LiDAR son lo que consume cada etapa del pipeline y se transfieren barato. Los
  16.8 GB de JPEG son entradas de una colorización **que ya se aplicó** — las
  nubes entregadas son `*_colorized` y la etapa 01 midió 0 % de puntos negros,
  así que el color ya está incorporado. Ninguna etapa del pipeline lee un JPEG.
- Los JPEG siguen siendo reproducibles igualmente: `ingest/od_download.py` los
  vuelve a traer del enlace compartido y verifica cada archivo contra el
  `quickXorHash` que publica el servicio. Eso es una garantía más fuerte que
  «alguien los subió una vez».
- Si alguna vez hacen falta en Drive, empaquetar cada carpeta `Camera/` en un
  solo archivo antes: 3 objetos en lugar de 18 095.

## Migración a Drive preservando el historial

La regla del planteamiento inicial —«no empezamos de cero, usamos
`dvc push --all-commits`»— es correcta y funciona. Una precisión que cambia el
cálculo de espacio:

> **El historial vive en la caché, no en el remoto local.** `dvc push` lee de
> `.dvc/cache`, que ya contiene todas las versiones que alguna vez se
> registraron con `dvc add`. El remoto local en D: es una *segunda* copia, no la
> fuente de la línea temporal. Si D: se llena, se puede borrar sin perder ni una
> sola versión.

```bash
# una vez exista la carpeta institucional en Drive
dvc remote add drive gdrive://<ID-DE-CARPETA>/dvcstore
dvc remote modify drive gdrive_client_id     '<...>.apps.googleusercontent.com'
dvc remote modify --local drive gdrive_client_secret '<secreto>'   # --local, siempre
dvc remote modify drive gdrive_acknowledge_abuse true

# toda la línea temporal, solo LiDAR
dvc push --all-commits --remote drive data/raw/Grupo03_crudo_2025/*/LiDAR.dvc
dvc push --all-commits --remote drive          # el resto de lo que produjo el pipeline

dvc remote default drive
git commit -am "config: Drive pasa a ser el remoto por defecto"
```

El `--local` del secreto de cliente no es opcional. Sin él, el secreto va a
`.dvc/config`, que **sí** se versiona; una vez publicado queda en el historial
para siempre y borrarlo no basta — hay que revocarlo.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Mover `data/` a `D:\...\dvc\` | Mover 20 GB entre particiones del mismo disco es una copia real, y mete el workspace dentro de la carpeta del remoto: dos cosas distintas compartiendo ruta. El remoto se direcciona por URL; no quiere el workspace dentro. |
| `cache.type = copy` (el defecto de DVC) | Necesita 40 GB en una partición con 28.6 GB libres. Falla. |
| Solo `cache.type = symlink` | Funciona entre particiones, pero en Windows los enlaces simbólicos exigen Modo Desarrollador o permisos de administrador, y que a un compañero le falte rompe el repo en silencio. Los enlaces duros no necesitan ninguno de los dos. |
| Un solo `dvc add data/raw` | Más simple, pero elimina la posibilidad de subir el LiDAR sin arrastrar 18 095 JPEG a Drive. |
| Saltarse el remoto local e ir directo a Drive | El 1 TB todavía no está disponible, y un remoto que no existe no se puede probar. Un `dvc pull` en un clon limpio es la única prueba real de que la configuración funciona. |

## Cómo comprobar que la decisión sigue en pie

```bash
dvc doctor                       # el tipo de caché debe reportarse como hardlink
dvc status -c                    # caché y remoto sincronizados
git ls-files | grep -E '\.(laz|jpg)$'    # no debe imprimir nada
```

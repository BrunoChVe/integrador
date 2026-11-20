# 0011 — Un EDA que cualquiera pueda regenerar con una sola instrucción

- **Estado:** aceptada
- **Fecha:** 2026-09-11
- **Afecta a:** `src/stages/s00_eda.py`, `tools/regenerar_eda.py`,
  etapa `eda` de `dvc.yaml`, bloque `eda` de `params.yaml`
- **Origen:** toda cifra que se cite sobre los datos tiene que ser verificable

## El requisito

Cualquiera clona el repositorio, ejecuta **una sola instrucción** y obtiene
**las mismas figuras y las mismas cifras** que se citaron en el informe o en la
reunión. Si una cifra no sale de ahí, no se puede defender.

Un notebook no cumple eso: depende del kernel, del orden en que se ejecutaron
las celdas y de quien lo corrió. Hacía falta una etapa del pipeline.

## Decisión

1. **Etapa DVC `eda` propia**, raíz del grafo, que lee **solo los `.laz`
   crudos**. No depende de la preparación, que tarda casi una hora: tiene que
   poder regenerarse en minutos.
2. **Determinista.** La muestra es cada k-ésimo archivo en orden de ruta y su
   primer bloque, sin aleatoriedad. La salida no lleva marcas de tiempo. Una
   salida con la fecha de ejecución no coincidiría nunca con la publicada.
3. **Las cifras se comparan en JSON, no en PNG.** Los bytes de una figura
   cambian entre máquinas por las fuentes instaladas, aunque el dibujo sea el
   mismo. `tools/regenerar_eda.py` compara campo a campo
   `reports/eda/eda.json` con la versión del último commit y dice cuáles
   difieren.
4. **Las figuras van a `docs/figuras_eda/`.** Son documentación, no datos, y
   deben verse en GitHub sin DVC. Es el mismo criterio que
   `docs/data_dictionary/dataset.md`: una salida de etapa que se versiona en Git
   (`cache: false`).
5. **La instrucción única corrige el intérprete.** En la máquina del propio
   equipo, el `python` que ve el shell de DVC en Windows era el entorno virtual
   de otro proyecto. `regenerar_eda.py` antepone al `PATH` el intérprete con que
   se la invoca antes de llamar a `dvc repro`.
6. **El inventario crudo pasa a MD5 calculado sobre los archivos**
   (`s01_catalog.py`). Antes se leía el hash del manifiesto del descargador,
   que solo existe en la máquina que descargó. En un clon limpio el inventario
   salía distinto.

## Por qué la definición de «verde» no se repite en el bloque `eda`

El EDA mide qué fracción de puntos tiene tono verde con los mismos umbrales que
la regla de la clase `green_area` (`weak_labels.green_area`, ver
[0010](0010-clase-area-verde.md)). Con dos definiciones, la figura del informe
y la regla podrían contar cosas distintas sin que nada lo avise.

## Cómo accede a los datos quien no los tiene

Por orden de preferencia:

1. **`dvc pull`** desde el remoto en Cloudflare R2, con un token de **solo
   lectura acotado al bucket**, entregado por un canal privado y revocable
   (`tools/configurar_r2.py --credenciales`).
2. **Copia directa de los `.laz`** en `data/raw/`, para quien no deba tener
   acceso al remoto.

## Consecuencias

- Añadir un escaneo obliga a añadir su carpeta `LiDAR` a las dependencias de la
  etapa en `dvc.yaml` y a `select.scans`.
- Si una cifra que se cita no está en `eda.json`, no es verificable. Se
  añade a la etapa, no se escribe a mano donde se vaya a citar.

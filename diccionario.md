<!-- Generado por etapa_3_preparacion/codigo/documentar.py (etapa `documentar` de dvc.yaml). No editar a mano: se sobrescribe en cada `dvc repro`. -->

# Diccionario de datos

El conjunto que produce la preparación son los **bloques** de 200 m: un archivo `.laz` por bloque y escaneo bajo `datos/intermedio/01_bloques/`, más un índice `bloque_index.csv` y la tabla final `datos/final/particion.csv`, que asigna cada bloque a train, valid o test. **Una fila es un punto** LiDAR; el bloque es la unidad de almacenamiento y de anotación ([ADR 0018](../decisiones/0018-el-bloque-de-anotacion-sustituye-a-la-tesela.md)). La versión de máquina es `diccionario.csv`.

Rangos medidos sobre 5 bloques de muestra (`informe.bloques_muestra`). Formato LAS 1.4, formato de punto 7, EPSG:32718.

## Punto (cada registro del `.laz`)

| campo | tipo | unidad | origen | mín | máx | descripción |
|---|---|---|---|---:|---:|---|
| `X` | int32 | m | crudo | 293 590 | 298 809.999 | Este UTM 18S. Guardado como entero con escala 0.001 m; se lee siempre en float64 (en float32 se perderian ~6 cm). |
| `Y` | int32 | m | crudo | 8 647 794.082 | 8 667 900.097 | Norte UTM 18S, misma escala y precision que X. |
| `Z` | int32 | m | crudo | -29.197 | 550.447 | Altura elipsoidal sin verificar (`project.vertical_datum`). Solo se usan alturas relativas, asi que el datum no afecta a las medidas de gálibo. |
| `intensity` | uint16 | - | crudo | 0 | 255 | Intensidad del retorno del laser, 0-255 en esta entrega. Sin calibrar por distancia. |
| `return_number` | uint8 | - | no se conserva | 0 | 0 | Descartado en `select.keep_dimensions` (Q3). Siempre 0 en el bloque. |
| `number_of_returns` | uint8 | - | no se conserva | 0 | 0 | Descartado en `select.keep_dimensions` (Q3). Siempre 0 en el bloque. |
| `synthetic` | uint8 | bandera | no se usa | 0 | 0 | Bandera LAS de punto sintetico. Siempre 0. |
| `key_point` | uint8 | bandera | no se usa | 0 | 0 | Bandera LAS de punto clave. Siempre 0. |
| `withheld` | uint8 | bandera | no se usa | 0 | 0 | Bandera LAS de punto retenido. Siempre 0. |
| `overlap` | uint8 | bandera | no se usa | 0 | 0 | Bandera LAS de solape entre pasadas. Siempre 0: el solape entre escaneos se resuelve con un bloque por escaneo, no marcando puntos. |
| `scanner_channel` | uint8 | - | no se usa | 0 | 0 | Canal del escaner (LAS 1.4). Siempre 0; el indice de laser va en point_source_id. |
| `scan_direction_flag` | uint8 | bandera | no se conserva | 0 | 0 | Constante en el crudo; descartado. |
| `edge_of_flight_line` | uint8 | bandera | no se conserva | 0 | 0 | Constante en el crudo; descartado. |
| `classification` | uint8 | id de clase | anotacion | 0 | 0 | Clase del punto segun `ontology.classes`. En el bloque vale 0 (sin clasificar, Q2); la anotacion escribe aqui el id de la clase. |
| `user_data` | uint8 | - | no se conserva | 0 | 0 | Constante en el crudo; descartado. |
| `scan_angle` | int16 | grados | no se usa | 0 | 0 | Angulo de escaneo. El crudo (formato 3) no lo trae util; siempre 0. |
| `point_source_id` | uint16 | - | crudo | 0 | 15 | Indice de laser del VLP-16, 0-15. Proxy debil del angulo vertical del rayo. Se perdia en silencio hasta 5fefd3f; aqui se comprueba que no vuelva a salir todo a 0. |
| `gps_time` | float64 | s | crudo | 315 833.399 | 593 003.380 | Tiempo GPS de la medida (segundos de la semana GPS). Ordena los puntos a lo largo de la trayectoria. |
| `red` | uint16 | - | crudo, reescalado | 0 | 65 280 | Canal rojo de la colorizacion por camara, 0-255 desplazado a 16 bits (Q4): valores multiplos de 256. |
| `green` | uint16 | - | crudo, reescalado | 0 | 65 280 | Canal verde, igual que red. |
| `blue` | uint16 | - | crudo, reescalado | 0 | 65 280 | Canal azul, igual que red. |

### Valores de `classification`

| id | clase | estado |
|---:|---|---|
| 0 | ruido_sin_clasificar | activa |
| 1 | pista | en_espera |
| 2 | vereda | en_espera |
| 3 | limite_construccion | en_espera |
| 4 | buzon | en_espera |
| 5 | poste_bt | activa |
| 6 | conductor_bt | en_espera |
| 7 | cable_telecom | en_espera |
| 8 | area_verde | en_espera |
| 9 | conductor_mt | en_espera |
| 10 | arbol | en_espera |
| 11 | poste_bt_luminaria | obsoleta |
| 12 | poste_mt | activa |
| 13 | luminaria | obsoleta |

Solo las clases `activa` se anotan y entran al entrenamiento ([ADR 0023](../decisiones/0023-solo-postes-con-su-luminaria.md)). La definición de cada una está en `etapa_3_preparacion/params.yaml: ontology.classes`.

## Índice de bloques (`bloque_index.csv`, 799 filas)

| columna | ejemplo | descripción |
|---|---|---|
| `scan` | `PACHAP01MT0108202501` | Escaneo de origen: nombre de su carpeta en datos/crudo. Un mismo suelo cubierto por dos escaneos da dos bloques. |
| `grupo` | `Grupo01_crudo_2025` | Entrega de la que viene el escaneo (primer nivel de datos/crudo). |
| `distrito` | `Pachacamac` | Distrito (segundo nivel de datos/crudo); vacio si la entrega no tiene ese nivel. |
| `bloque_ix` | `1493` | Indice de columna de la rejilla: floor(este / bloque_m). |
| `bloque_iy` | `43239` | Indice de fila de la rejilla: floor(norte / bloque_m). |
| `path` | `datos/intermedio/01_bloques/Grupo01_crudo_2025/Pachacamac/PACHAP01MT0108202501/b_1493_43239.laz` | Ruta del .laz del bloque, relativa a la raiz del repositorio. |
| `points_total` | `915726` | Puntos del archivo, nucleo mas anillo de contexto. |
| `points_core` | `202657` | Puntos dentro del cuadrado de bloque_m, sin anillo. |
| `min_x` | `298600.0` | Este de la esquina SO del nucleo (m, UTM 18S). |
| `min_y` | `8647800.0` | Norte de la esquina SO del nucleo (m, UTM 18S). |
| `bloque_m` | `200.0` | Lado del nucleo (m), `tiling.bloque_m`. |
| `buffer_m` | `10.0` | Ancho del anillo de contexto (m), `tiling.buffer_m`. |
| `min_z` | `-29.197000000000003` | Z minima de los puntos del bloque (m). |
| `max_z` | `209.565` | Z maxima de los puntos del bloque (m). |
| `density_core_pts_m2` | `5.1` | points_core / bloque_m^2. |

## Tabla final (`datos/final/particion.csv`, 799 filas)

| columna | ejemplo | descripción |
|---|---|---|
| `path` | `datos/intermedio/01_bloques/Grupo01_crudo_2025/Pachacamac/PACHAP01MT0108202501/b_1493_43239.laz` | Ruta del .laz del bloque; enlaza con bloque_index.csv. |
| `scan` | `PACHAP01MT0108202501` | Escaneo de origen. |
| `distrito` | `Pachacamac` | Distrito de origen. |
| `bloque_ix` | `1493` | Columna de la rejilla de bloques. |
| `bloque_iy` | `43239` | Fila de la rejilla de bloques. |
| `supercelda` | `s_298_8647` | Celda de `particion.supercelda_m` que contiene al bloque: la unidad que se asigna entera a una particion. |
| `points_core` | `202657` | Puntos de nucleo del bloque, para pesar las particiones. |
| `particion` | `train` | train, valid o test. |

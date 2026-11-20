# 0003 — Ajustar el suelo antes de limpiar, no después

- **Estado:** aceptada
- **Fecha:** 2026-09-06
- **Afecta a:** el orden de etapas en `dvc.yaml`, `params.yaml: ground.*`,
  `clean.z_clip`

## Decisión

La etapa `ground` (03) se ejecuta **antes** que `clean` (04). El planteamiento
inicial daba a entender el orden contrario.

## Por qué

Los umbrales que hacen segura la limpieza están expresados como altura *sobre el
suelo*, no como Z absoluta:

```yaml
clean:
  z_clip:
    min_above_ground_m: -1.5
    max_above_ground_m: 30.0
```

La Z absoluta no sirve. Los escaneos abarcan 92 m de desnivel, así que `z = 405`
significa «superficie de la pista» en una tesela y «techo» en otra. Un recorte
sobre Z absoluta borraría estructura real en las teselas altas y nada en las
bajas.

Por tanto, la superficie del terreno tiene que existir antes de que se pueda
ejecutar el primer filtro.

## Cómo se ajusta la superficie

Al ser datos de retorno único (hallazgo Q3), el truco estándar de la
fotogrametría aérea —tratar el último retorno como suelo— no está disponible. La
superficie se ajusta geométricamente:

1. **Rejilla de percentil bajo**, no mínimo estricto. `ground.percentile: 5.0`
   sobre celdas de 1 m. Un mínimo estricto queda capturado por un solo punto de
   ruido bajo suelo por celda, lo que hunde la superficie y después reporta cada
   punto de suelo real como si estuviera 30 cm «sobre el suelo».
2. **Relleno por difusión** de las celdas sin retornos — frecuentes aquí, porque
   los autos estacionados ocluyen la acera de forma continua.
3. **Suavizado por mediana**, `smooth_iterations: 3` sobre una ventana de 5
   celdas.
4. **Limitación de pendiente** a 25 grados, para que una fachada o un camión no
   puedan levantar la superficie.

`ground.cell_m: 1.0` resuelve un sardinel. `ground_tolerance_m: 0.08` está
deliberadamente por debajo de la altura típica de sardinel en Lima
(0.12-0.20 m): por encima, las veredas se absorben en la pista y las clases 1 y
2 dejan de ser separables.

## Resultado medido

Sobre las 36 teselas de la fase 1: fracción de suelo media del **22 %**, mediana
del percentil 99 de HAG alrededor de 10 m, HAG máxima de 35.5 m.

El 22 % es plausible para un cañón urbano: la mayoría de los retornos son
fachadas, vehículos y cables, no pavimento. Si esta cifra llegara a superar el
~60 %, probablemente la superficie se habría ajustado a un techo.

## Consecuencia

`height_above_ground` queda disponible para todas las etapas posteriores y es el
rasgo más fuerte de la ontología:

| Clase | HAG típica |
|---|---|
| pista, vereda, buzón | 0.0 - 0.2 m |
| poste | 0 - 12 m, continuo en Z |
| haz de telecom | ~5 - 7 m |
| conductor eléctrico | ~7 - 11 m |

## Cómo verificarlo

```bash
python src/viewer/view_tile.py --stage ground --color hag
```

La pista debe verse uniformemente oscura, las fachadas deben formar gradientes
verticales, y los cables deben aparecer como líneas horizontales brillantes a
una altura consistente. Una tesela donde la pista **no** salga plana en esta
vista tiene un mal ajuste de suelo.

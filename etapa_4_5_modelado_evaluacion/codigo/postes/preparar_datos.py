"""Construye la cache de voxeles con rasgos y etiqueta para todos los bloques
de `datos/crudo/etiquetado/`. Se ejecuta una vez (unos minutos por bloque); el cuaderno
`cuadernos/baseline_geometrico.ipynb` lee de `datos/intermedio/cache/geometrica/` y no vuelve a tocar las nubes.

    python codigo/postes/preparar_datos.py            # los que falten
    python codigo/postes/preparar_datos.py --forzar   # todos otra vez
    python codigo/postes/preparar_datos.py PACHAP01MT0108202501_b_1493_43239
    python codigo/postes/preparar_datos.py --solo-etiquetas   # Y con los recortes de hoy

Si un recorte es mas nuevo que la cache de su bloque, se recalcula solo la
etiqueta (los rasgos no dependen de ella).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from postes_datos import (CACHE, bloques_en_cache, etiquetas_desactualizadas, inventario,  # noqa: E402
                          preparar_bloque, guardar_cache, reetiquetar_cache, resumen_cache, ruta_cache)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bloques", nargs="*", help="solo estos bloques (por defecto todos)")
    ap.add_argument("--forzar", action="store_true", help="rehacer aunque ya esten en cache")
    ap.add_argument("--solo-etiquetas", action="store_true",
                    help="recalcular solo la etiqueta de los bloques ya en cache")
    a = ap.parse_args()

    inv = inventario()
    if a.bloques:
        inv = inv[inv["bloque"].isin(a.bloques)]
    ya = inv["bloque"].isin(bloques_en_cache())
    pendientes = inv if a.forzar else inv[~ya]
    viejas = inv[ya & (a.solo_etiquetas | inv.apply(
        lambda f: etiquetas_desactualizadas(f.to_dict(), ruta_cache(f["bloque"])), axis=1))]
    if a.forzar:
        viejas = viejas.iloc[0:0]
    if a.solo_etiquetas:
        pendientes = pendientes.iloc[0:0]
    print(f"{len(inv)} bloques en datos/crudo/etiquetado/, {len(pendientes)} por preparar, "
          f"{len(viejas)} por reetiquetar -> {CACHE}")
    for _, fila in viejas.iterrows():
        reetiquetar_cache(fila.to_dict())
    sin_etiqueta = inv[inv["BT"].isna() & inv["MT"].isna()]["bloque"].tolist()
    if sin_etiqueta:
        print(f"  AVISO: sin ningun recorte (todo contara como fondo): {sin_etiqueta}")

    for _, fila in pendientes.iterrows():
        d = preparar_bloque(fila.to_dict())
        guardar_cache(d)
        del d

    res = resumen_cache()
    res.to_csv(CACHE / "resumen.csv", index=False)
    with __import__("pandas").option_context("display.width", 200, "display.max_columns", 20):
        print("\n", res.to_string(index=False))


if __name__ == "__main__":
    main()

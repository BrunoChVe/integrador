"""Conecta DVC con Cloudflare R2.

R2 habla la API de S3, así que DVC lo usa con el conector `dvc-s3` y un
`endpointurl` propio. Es el mismo procedimiento que con S3:
cambian la URL y dos líneas.

Dos usos, con permisos distintos:

  1) Una sola vez, quien administra el bucket, crea el remoto. Lo que escribe
     en .dvc/config NO es secreto y se versiona, para que todo clon sepa dónde
     están los datos:

        python etapa_3_preparacion/herramientas/configurar_r2.py --crear-remoto \\
            --account-id <ID-DE-CUENTA> --bucket <NOMBRE-DEL-BUCKET>
        git add .dvc/config && git commit -m "config: remoto DVC en Cloudflare R2"

  2) Cada persona pone SUS credenciales. Van a
     .dvc/config.local, que Git ignora. Una clave que llega al historial ya no
     se puede retirar: hay que revocarla.

        python etapa_3_preparacion/herramientas/configurar_r2.py --credenciales

     A quien solo deba leer se le da un token de SOLO LECTURA acotado al
     bucket (Cloudflare > R2 > Manage API tokens > "Object Read only"),
     revocable en cualquier momento.

Tras configurar, comprueba la conexión con `dvc status --cloud`.
"""

from __future__ import annotations

import argparse
import getpass
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]   # raiz del repo: ahi esta .dvc/
REMOTO = "r2"


def dvc(*args, silencioso=False):
    r = subprocess.run([sys.executable, "-m", "dvc", *args], cwd=RAIZ,
                       capture_output=True, text=True, errors="ignore")
    if r.returncode != 0 and not silencioso:
        print(f"  [X] dvc {' '.join(args[:3])} ...: {(r.stderr or r.stdout).strip()[-300:]}")
    return r


def remoto_existe() -> bool:
    return REMOTO in dvc("remote", "list", silencioso=True).stdout.split()


def normalizar_account_id(valor: str) -> str:
    """Acepta el ID pelado o el endpoint completo pegado del panel.

    Pegar la URL entera es el error facil de cometer, y el sintoma aparece
    tarde y confuso: DVC intenta conectarse a un host como
    `https://https:/<id>.r2.cloudflarestorage.com.r2.cloudflarestorage.com`.
    """
    v = valor.strip().strip("/")
    for prefijo in ("https://", "http://"):
        if v.startswith(prefijo):
            v = v[len(prefijo):]
    v = v.split("/")[0]
    if v.endswith(".r2.cloudflarestorage.com"):
        v = v[: -len(".r2.cloudflarestorage.com")]
    return v


def crear_remoto(account_id: str, bucket: str, prefijo: str, por_defecto: bool) -> bool:
    account_id = normalizar_account_id(account_id)
    if not re.fullmatch(r"[0-9a-f]{32}", account_id):
        print(f"  [X] '{account_id}' no parece un Account ID de Cloudflare.")
        print("      Son 32 caracteres hexadecimales, los que van ANTES de")
        print("      .r2.cloudflarestorage.com en el endpoint S3 del bucket.")
        return False
    url = f"s3://{bucket}/{prefijo}".rstrip("/")
    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    if remoto_existe():
        dvc("remote", "modify", REMOTO, "url", url)
    else:
        args = ["remote", "add"] + (["-d"] if por_defecto else []) + [REMOTO, url]
        if dvc(*args).returncode != 0:
            return False
    for k, v in (("endpointurl", endpoint), ("region", "auto")):
        if dvc("remote", "modify", REMOTO, k, v).returncode != 0:
            return False
    if por_defecto:
        dvc("remote", "default", REMOTO)
    print(f"  Remoto '{REMOTO}' -> {url}")
    print(f"  endpoint          -> {endpoint}")
    print("  Escrito en .dvc/config (no secreto). Versiónalo con git.")
    return True


def poner_credenciales(key_id: str | None, secret: str | None) -> bool:
    if not remoto_existe():
        print(f"  [X] No existe el remoto '{REMOTO}' en .dvc/config.")
        print("      Actualiza el repositorio (git pull) o créalo con --crear-remoto.")
        return False
    key_id = key_id or input("  Access Key ID: ").strip()
    secret = secret or getpass.getpass("  Secret Access Key (no se muestra): ").strip()
    if not key_id or not secret:
        print("  [X] Credenciales vacías.")
        return False
    for k, v in (("access_key_id", key_id), ("secret_access_key", secret)):
        if dvc("remote", "modify", "--local", REMOTO, k, v).returncode != 0:
            return False
    print("  Credenciales guardadas en .dvc/config.local (ignorado por Git).")
    return True


def comprobar() -> None:
    print("\n  Comprobando la conexión (dvc status --cloud)...")
    r = dvc("status", "--cloud", "-r", REMOTO, silencioso=True)
    salida = (r.stdout + r.stderr).strip()
    if r.returncode == 0:
        print("  OK: el remoto responde.")
        print("  " + "\n  ".join(salida.splitlines()[:6]))
        return
    print("  [X] El remoto no responde:")
    print("  " + "\n  ".join(salida.splitlines()[-4:]))
    if "checksum" in salida.lower() or "notimplemented" in salida.lower():
        print("\n  Posible incompatibilidad de sumas de verificación entre botocore y R2.")
        print("  Prueba antes de repetir:")
        print("    set AWS_REQUEST_CHECKSUM_CALCULATION=when_required")
        print("    set AWS_RESPONSE_CHECKSUM_VALIDATION=when_required")


def main() -> int:
    ap = argparse.ArgumentParser(description="Conecta DVC con Cloudflare R2.")
    ap.add_argument("--crear-remoto", action="store_true",
                    help="escribe el remoto en .dvc/config (una vez, quien administra)")
    ap.add_argument("--credenciales", action="store_true",
                    help="guarda tus credenciales en .dvc/config.local")
    ap.add_argument("--account-id", help="ID de cuenta de Cloudflare")
    ap.add_argument("--bucket", help="nombre del bucket R2")
    ap.add_argument("--prefijo", default="dvcstore", help="carpeta dentro del bucket")
    ap.add_argument("--no-por-defecto", action="store_true",
                    help="no convertir R2 en el remoto por defecto")
    ap.add_argument("--access-key-id")
    ap.add_argument("--secret-access-key")
    args = ap.parse_args()

    if not (args.crear_remoto or args.credenciales):
        ap.print_help()
        return 2
    if args.crear_remoto:
        if not (args.account_id and args.bucket):
            print("  [X] --crear-remoto necesita --account-id y --bucket")
            return 2
        if not crear_remoto(args.account_id, args.bucket, args.prefijo,
                            not args.no_por_defecto):
            return 1
    if args.credenciales:
        if not poner_credenciales(args.access_key_id, args.secret_access_key):
            return 1
        comprobar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

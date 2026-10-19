"""Extrae de tu buzón TODOS los servicios donde te registraste.

Por qué existe: Holehe comprueba 121 servicios y Epieos unos pocos. **Ningún
tool externo te dará la lista completa**, porque cada servicio decide si
responde o no. En cambio, tu buzón **sí es completo**: a todos los servicios
donde te registraste les llegó (o te llegó) un correo.

Uso:
    1) Exporta tus correos con Google Takeout (o el buzón que quieras)
       → Google Takeout → Mail → descarga el .mbox
    2) python3 mailbox_services.py MiCorreo.mbox --out servicios.csv

También acepta una carpeta con archivos .eml.

Salida: CSV con dominio;primer_correo;ultimo_correo;nº_correos;parece_registro;ejemplos
"""
import argparse
import csv
import mailbox
import re
from collections import defaultdict
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

# Palabras típicas de un correo de registro / bienvenida / verificación
REGISTRO = (
    "bienvenid", "welcome", "verifica", "verify", "confirma", "confirm",
    "activa", "activate", "activación", "registro", "sign up", "signup",
    "cuenta creada", "account created", "new account", "valida", "validate",
    "bienvenue", "willkommen", "benvenuto", "check your email", "magic link",
    "password", "contraseña", "código", "code is", "otp", "one-time",
)

# Dominios que NO son "un servicio donde me registré"
IGNORAR = {
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com",
    "live.com", "msn.com", "aol.com", "protonmail.com", "proton.me",
    "sendgrid.net", "mailchimp.com", "amazonses.com", "mandrillapp.com",
    "mcsv.net", "rsgsv.net", "sparkpostmail.com", "mailgun.org",
    "googlemail.com", "google.com", "apple.com", "notification", "localhost",
}

# Subdominios que se quitan para quedarse con el servicio real
SUB = ("mail.", "email.", "em.", "e.", "mg.", "mailer.", "mailing.", "news.",
       "newsletter.", "info.", "notifications.", "notify.", "account.",
       "accounts.", "noreply.", "no-reply.", "member.", "members.", "hello.",
       "team.", "support.", "s.", "t.", "click.", "links.", "mkt.", "marketing.",
       "campaign.", "campaigns.", "updates.", "update.", "message.", "messages.")

DOS_NIVELES = {"co.uk", "com.mx", "com.co", "com.ar", "com.br", "com.es",
               "com.au", "co.jp", "co.in", "com.pe", "com.cl", "com.ec"}


def dominio_raiz(host: str) -> str:
    host = (host or "").lower().strip().rstrip(".")
    if not host or "." not in host:
        return host
    partes = host.split(".")
    if len(partes) >= 3 and ".".join(partes[-2:]) in DOS_NIVELES:
        base = ".".join(partes[-3:])
    else:
        base = ".".join(partes[-2:])
    for s in SUB:
        if base.startswith(s):
            base = base[len(s):]
    return base


def iter_mensajes(ruta: Path):
    """Itera los correos de un .mbox o de una carpeta con .eml."""
    if ruta.is_dir():
        for p in ruta.rglob("*.eml"):
            import email
            with p.open("rb") as fh:
                yield email.message_from_binary_file(fh)
        return
    caja = mailbox.mbox(str(ruta))
    caja.lock()
    try:
        for msg in caja:
            yield msg
    finally:
        caja.unlock()


def main() -> int:
    ap = argparse.ArgumentParser(description="Servicios donde te registraste, desde tu buzón")
    ap.add_argument("origen", help="archivo .mbox o carpeta con .eml")
    ap.add_argument("--out", default="servicios.csv", help="CSV de salida")
    ap.add_argument("--min", type=int, default=1, help="mínimo de correos para listar (1)")
    args = ap.parse_args()

    origen = Path(args.origen)
    if not origen.exists():
        print(f"❌ No existe: {origen}")
        return 1

    datos = defaultdict(lambda: {"n": 0, "primero": None, "ultimo": None,
                                 "registro": False, "asuntos": []})

    total = 0
    for msg in iter_mensajes(origen):
        total += 1
        _, addr = parseaddr(msg.get("From", "") or "")
        if "@" not in addr:
            continue
        dom = dominio_raiz(addr.split("@")[-1])
        if not dom or dom in IGNORAR:
            continue
        asunto = str(msg.get("Subject", "") or "")[:120]
        texto = (asunto + " " + str(msg.get("Body", ""))[:0]).lower()
        es_registro = any(p in texto for p in REGISTRO)

        fecha = None
        try:
            dt = parsedate_to_datetime(msg.get("Date", ""))
            fecha = dt.date().isoformat()
        except (TypeError, ValueError):
            pass

        d = datos[dom]
        d["n"] += 1
        d["registro"] = d["registro"] or es_registro
        if len(d["asuntos"]) < 2 and asunto:
            d["asuntos"].append(asunto[:60])
        if fecha:
            if not d["primero"] or fecha < d["primero"]:
                d["primero"] = fecha
            if not d["ultimo"] or fecha > d["ultimo"]:
                d["ultimo"] = fecha

    filas = [(dom, v) for dom, v in datos.items() if v["n"] >= args.min]
    filas.sort(key=lambda kv: (kv[1]["primero"] or "9999", kv[0]))

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Dominio", "Primer_correo", "Ultimo_correo", "N_Correos",
                    "Parece_registro", "Ejemplos_de_asunto"])
        for dom, v in filas:
            w.writerow([dom, v["primero"] or "", v["ultimo"] or "", v["n"],
                        "SI" if v["registro"] else "",
                        " | ".join(v["asuntos"])])

    print(f"\n✓ {total:,} correos leídos · {len(filas)} servicios encontrados")
    print(f"✓ CSV: {args.out}\n")
    print(f"{'DOMINIO':<34} {'1er correo':<12} {'correos':>7}  registro")
    print("─" * 70)
    for dom, v in filas[:40]:
        print(f"  {dom:<32} {(v['primero'] or '?'):<12} {v['n']:>7}  "
              f"{'✅' if v['registro'] else ''}")
    if len(filas) > 40:
        print(f"  … y {len(filas) - 40} más en el CSV")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

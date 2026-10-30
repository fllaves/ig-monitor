"""Quién te etiqueta en POSTS y REELS (página /tagged/).

La página pública `instagram.com/<usuario>/tagged/` lista las publicaciones donde
te etiquetan. Cada enlace tiene la forma:

    /<autor>/p/<shortcode>/      → post
    /<autor>/reel/<shortcode>/   → reel

Así que **el autor viene en el propio enlace**: no hace falta abrir cada post.

Uso:
    python3 tagged.py                 # escanea y muestra
    python3 tagged.py --notify        # además lo manda por Telegram
    python3 tagged.py --headless      # sin ventana (para la rutina)
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config

RE_LINK = re.compile(r"^/([A-Za-z0-9._]{2,40})/(p|reel)/([A-Za-z0-9_-]{5,20})/?$")


def _cookies() -> dict:
    p = Path("data/cookies.json")
    if not p.exists():
        raise SystemExit("Falta data/cookies.json.\n"
                         "Genera la sesión con:  python3 story_archive.py --save-cookies")
    return json.loads(p.read_text())


def scan(usuario: str, headless: bool = True, espera: float = 8.0) -> list:
    """Devuelve las publicaciones en las que te etiquetan."""
    from playwright.sync_api import sync_playwright

    cookies = _cookies()
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=headless)
        try:
            ctx = b.new_context(locale="es-ES", viewport={"width": 1280, "height": 900})
            ctx.add_cookies([{"name": k, "value": v,
                              "domain": ".instagram.com", "path": "/"}
                             for k, v in cookies.items()])
            page = ctx.new_page()
            page.goto(f"https://www.instagram.com/{usuario}/tagged/",
                      wait_until="domcontentloaded")
            time.sleep(espera)
            enlaces = page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.getAttribute('href'))
                    .filter(h => h && (h.includes('/p/') || h.includes('/reel/')))""")
        finally:
            b.close()

    fuera = {}
    for h in enlaces:
        m = RE_LINK.match(str(h))
        if not m:
            continue
        autor, tipo, code = m.groups()
        if autor.lower() == usuario.lower():
            continue          # una publicación propia no es "me etiquetaron"
        fuera[f"{autor}/{tipo}/{code}"] = {
            "id": f"{autor}/{tipo}/{code}",
            "autor": autor,
            "tipo": "reel" if tipo == "reel" else "post",
            "code": code,
            "url": f"https://instagram.com/{autor}/{tipo}/{code}/",
        }
    return list(fuera.values())


def guardar(items: list) -> int:
    """Guarda en la base; devuelve cuántas son NUEVAS."""
    import storage
    conn = storage._connect()
    nuevas = 0
    ahora = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS tagged_posts (
            id TEXT PRIMARY KEY, autor TEXT, tipo TEXT, url TEXT,
            first_seen TEXT, last_seen TEXT)""")
        for it in items:
            existe = conn.execute("SELECT 1 FROM tagged_posts WHERE id=?", (it["id"],)).fetchone()
            if existe:
                conn.execute("UPDATE tagged_posts SET last_seen=? WHERE id=?", (ahora, it["id"]))
            else:
                conn.execute("INSERT INTO tagged_posts(id,autor,tipo,url,first_seen,last_seen)"
                             " VALUES (?,?,?,?,?,?)",
                             (it["id"], it["autor"], it["tipo"], it["url"], ahora, ahora))
                nuevas += 1
        conn.commit()
    finally:
        storage._close(conn)
    return nuevas


def informe(items: list, nuevas: int) -> str:
    hoy = datetime.now().strftime("%d %b %Y")
    if not items:
        return f"🏷️ Etiquetas · {hoy}\n\nNadie te etiquetó en posts ni reels."
    lineas = [f"🏷️ **Te etiquetaron · {hoy}**", ""]
    for it in sorted(items, key=lambda x: x["autor"]):
        icono = "🎬" if it["tipo"] == "reel" else "🖼️"
        lineas.append(f"{icono} **@{it['autor']}** ({it['tipo']})")
        lineas.append(f"   {it['url']}")
    lineas.append("")
    lineas.append(f"Total: {len(items)} etiqueta(s) · {nuevas} nueva(s) hoy")
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser(description="Quién te etiqueta en posts y reels")
    ap.add_argument("--usuario", default="", help="tu usuario (por defecto, el de config)")
    ap.add_argument("--headless", action="store_true", help="sin ventana del navegador")
    ap.add_argument("--notify", action="store_true", help="envía el informe por Telegram")
    ap.add_argument("--no-save", action="store_true", help="no guardar en la base")
    args = ap.parse_args()

    usuario = args.usuario or config.real_username(config.to_code(config.USERNAME))
    print(f"→ etiquetas de @{usuario}…")
    try:
        items = scan(usuario, headless=args.headless)
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ no pude leer /tagged/: {exc}", file=sys.stderr)
        return 1

    print(f"  {len(items)} publicación(es) donde te etiquetan")
    for it in items:
        print(f"    {it['tipo']:<5} @{it['autor']:<22} {it['url']}")

    nuevas = 0
    if not args.no_save and items:
        try:
            nuevas = guardar(items)
            print(f"  → guardadas en la base ({nuevas} nuevas)")
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ no pude guardar: {exc}", file=sys.stderr)

    if args.notify:
        try:
            import notify
            ok, info = notify.send_telegram(informe(items, nuevas))
            print(f"  → Telegram: {'✅ enviado' if ok else '⚠️ ' + info}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ notify: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

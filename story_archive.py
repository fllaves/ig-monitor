"""Archivador de HISTORIAS: las captura antes de que expiren (24 h).

Por qué existe: las historias desaparecen. Dolphin Radar las muestra porque las
archiva el mismo día; si no las capturas hoy, se pierden para siempre.

Usa un navegador real (Playwright) con la sesión de la cuenta burner y guarda:
  · quién la publicó y cuándo (fecha original)
  · si te menciona (etiqueta de mención)
  · si incluye enlaces
  · la URL del medio y, opcionalmente, lo DESCARGA a disco

⚠️ Va contra los ToS de Instagram. Riesgo para la cuenta burner. Ritmo lento.

Instalación (una vez):
    pip3 install --user playwright browser_cookie3
    python3 -m playwright install chromium

Uso (cierra Brave antes):
    python3 story_archive.py --accounts PP,BC,DRZ --debug
    python3 story_archive.py --accounts PP,BC --media-dir data/stories
"""
import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://www.instagram.com"

# JS: datos del visor de historias actual
JS_STORY = """
() => {
  const out = {video: null, images: [], links: [], header: ''};
  const v = document.querySelector('video');
  if (v) out.video = v.currentSrc || v.src || null;
  document.querySelectorAll('img').forEach(i => {
    const s = i.currentSrc || i.src;
    if (s && s.startsWith('http')) out.images.push(s);
  });
  document.querySelectorAll('a[href]').forEach(a => {
    const h = a.getAttribute('href');
    if (!h) return;
    if (h.startsWith('http')) out.links.push(h);
    else if (/^\\/[A-Za-z0-9._]+\\/$/.test(h)) out.links.push(h);
  });
  const h = document.querySelector('header, time');
  if (h) out.header = (h.innerText || '').slice(0, 120);
  return out;
}
"""


def load_cookies(browser: str) -> dict:
    try:
        import browser_cookie3
    except ImportError:
        raise SystemExit("Falta browser_cookie3:\n    pip3 install --user requests browser_cookie3")
    fn = getattr(browser_cookie3, browser, None)
    if fn is None:
        raise SystemExit(f"Navegador no soportado: {browser}")
    print(f"→ Leyendo cookies de {browser}…")
    cookies = {c.name: c.value for c in fn(domain_name="instagram.com")}
    if "sessionid" not in cookies:
        raise SystemExit("No encontré 'sessionid'. ¿Cerraste el navegador?")
    print(f"  ✔ Sesión encontrada (usuario id {cookies.get('ds_user_id', '?')})")
    return cookies


def _iso(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _clasificar(links, me):
    """Separa menciones (internas) de enlaces externos."""
    mentions, externos = [], []
    for h in links or []:
        if h.startswith("http"):
            if "instagram.com" in h:
                m = re.search(r"instagram\\.com/([A-Za-z0-9._]+)/?", h)
                if m:
                    mentions.append(m.group(1).lower())
            else:
                externos.append(h)
        elif re.match(r"^/[A-Za-z0-9._]+/?$", h):
            mentions.append(h.strip("/").lower())
    mentions = [m for m in dict.fromkeys(mentions) if m not in ("p", "reel", "stories", "explore")]
    return mentions, list(dict.fromkeys(externos))


def capture_account(page, ctx, username, me, max_stories, media_dir, debug):
    """Recorre las historias de una cuenta y devuelve las capturadas."""
    encontradas = []
    url = f"{BASE}/stories/{username}/"
    page.goto(url, wait_until="domcontentloaded")
    time.sleep(4)

    for i in range(max_stories):
        try:
            data = page.evaluate(JS_STORY) or {}
        except Exception as exc:  # noqa: BLE001
            print(f"    ⚠ no pude leer la historia: {exc}", file=sys.stderr)
            break

        html = page.content()
        taken = re.findall(r'"taken_at":(\d{9,11})', html)
        pk = re.findall(r'"pk":"?(\d{15,20})"?', html)
        story_pk = pk[0] if pk else f"{username}-{i}"
        mentions, externos = _clasificar(data.get("links"), me)
        media_url = data.get("video") or (data.get("images") or [None])[-1]

        if media_url or mentions or externos:
            kind = "video" if data.get("video") else "image"
            media_path = ""
            if media_dir and media_url:
                ext = ".mp4" if kind == "video" else ".jpg"
                destino = Path(media_dir) / f"{username}_{story_pk}{ext}"
                try:
                    resp = ctx.request.get(media_url, timeout=60000)
                    if resp.ok:
                        destino.parent.mkdir(parents=True, exist_ok=True)
                        destino.write_bytes(resp.body())
                        media_path = str(destino)
                except Exception as exc:  # noqa: BLE001
                    if debug:
                        print(f"    (no pude descargar el medio: {exc})")

            encontradas.append({
                "story_id": f"{username}-{story_pk}",
                "username": username,
                "pk": str(story_pk),
                "taken_at": _iso(taken[0]) if taken else datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                "media_url": media_url or "",
                "media_path": media_path,
                "mentions": mentions,
                "mentions_me": 1 if me and me in [m.lower() for m in mentions] else 0,
                "links": externos,
                "caption": "",
                "url": page.url,
            })
            marca = ""
            if me and me in [m.lower() for m in mentions]:
                marca = " ⬅️ TE MENCIONA"
            elif externos:
                marca = " 🔗 con enlace"
            print(f"    · historia {i + 1}: {kind}{marca}")

        if debug:
            print(f"      (pk={story_pk}, links={len(data.get('links') or [])}, "
                  f"taken={'sí' if taken else 'no'})")

        # Siguiente historia
        try:
            page.keyboard.press("ArrowRight")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(random.uniform(1.5, 3.0))

        # Si la URL cambió de cuenta o volvimos al inicio, paramos
        if "/stories/" not in page.url:
            break

    return encontradas


def main() -> int:
    ap = argparse.ArgumentParser(description="Archivador de historias de Instagram")
    ap.add_argument("--accounts", required=True,
                    help="cuentas a archivar (códigos o usuarios), separadas por comas")
    ap.add_argument("--me", default="", help="tu usuario, para detectar menciones")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--out", default="story_archive.json")
    ap.add_argument("--media-dir", default="", help="carpeta donde descargar los medios")
    ap.add_argument("--max-stories", type=int, default=40)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("Falta playwright:\n    pip3 install --user playwright\n"
                     "    python3 -m playwright install chromium")

    import config

    cuentas = [config.real_username(a.strip()) for a in args.accounts.split(",") if a.strip()]
    me = (args.me or config.USERNAME or "").strip().lstrip("@").lower()
    cookies = load_cookies(args.browser)
    pw_cookies = [{"name": k, "value": v, "domain": ".instagram.com", "path": "/"}
                  for k, v in cookies.items()]

    print("=" * 64)
    print("  ARCHIVADOR DE HISTORIAS · ⚠️  ToS + riesgo para la burner")
    print("=" * 64)

    todas = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(locale="es-ES", viewport={"width": 1280, "height": 900})
        ctx.add_cookies(pw_cookies)
        page = ctx.new_page()
        for name in cuentas:
            print(f"→ @{config.to_code(name)}")
            try:
                todas.extend(capture_account(page, ctx, name, me, args.max_stories,
                                             args.media_dir, args.debug))
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠ {name}: {exc}", file=sys.stderr)
        browser.close()

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(todas, fh, ensure_ascii=False, indent=1)

    menciones = sum(1 for s in todas if s["mentions_me"])
    print(f"\n→ Capturadas {len(todas)} historias ({menciones} te mencionan) → {args.out}")

    if todas:
        try:
            import storage
            n = storage.save_story_archive(todas)
            print(f"→ Guardadas en la base: {n}")
            print("  (o impórtalas en el panel → 📸 Archivo de historias)")
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ no pude guardar en la base: {exc}", file=sys.stderr)
    else:
        print("  No se capturó nada. ¿Tienen historias activas ahora mismo?")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

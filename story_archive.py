"""Archivador de HISTORIAS: las captura antes de que expiren (24 h).

Por qué existe: las historias desaparecen. Dolphin Radar las muestra porque las
archiva el mismo día; si no las capturas hoy, se pierden para siempre.

Usa un navegador real (Playwright) con la sesión de la cuenta burner y guarda:
  · quién la publicó y cuándo (fecha original)
  · si te menciona (etiqueta de mención)
  · si incluye enlaces
  · la URL del medio y, opcionalmente, lo DESCARGA a disco

Privacidad: los archivos y registros usan **códigos** (PP/BC/DRZ…), nunca el
usuario real.

⚠️ Va contra los ToS de Instagram. Riesgo para la cuenta burner. Ritmo lento.

Instalación (una vez):
    pip3 install --user playwright browser_cookie3
    python3 -m playwright install chromium

Uso (cierra Brave antes):
    python3 story_archive.py --accounts PP,BC,DRZ --media-dir data/stories --debug
"""
import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://www.instagram.com"
# Un medio de historia real ocupa mucho más que un avatar (150×150 = 22.500 px²)
AREA_MINIMA = 90_000

# JS: datos del visor de historias (elige la imagen MÁS GRANDE, no la última)
JS_STORY = """
() => {
  const out = {video: null, best: null, bestArea: 0, links: [], total: 0};
  const v = document.querySelector('video');
  if (v) out.video = v.currentSrc || v.src || null;
  document.querySelectorAll('img').forEach(i => {
    const s = i.currentSrc || i.src;
    if (!s || !s.startsWith('http')) return;
    out.total += 1;
    const w = i.naturalWidth || 0, h = i.naturalHeight || 0;
    if (w * h > out.bestArea) { out.bestArea = w * h; out.best = s; }
  });
  document.querySelectorAll('a[href]').forEach(a => {
    const h = a.getAttribute('href');
    if (!h) return;
    if (h.startsWith('http')) out.links.push(h);
    else if (/^\\/[A-Za-z0-9._]+\\/$/.test(h)) out.links.push(h);
  });
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


def _mentions_from_html(html: str) -> list:
    """Extrae las menciones REALES (stickers) del JSON embebido de la historia.

    Los enlaces del DOM incluyen navegación, sugerencias y cuentas relacionadas,
    así que producían falsos positivos. El JSON sí trae las menciones de verdad.
    """
    nombres = []
    for clave in ("reel_mentions", "story_mentions"):
        for m in re.finditer(rf'"{clave}":\s*\[', html):
            trozo = html[m.end():m.end() + 4000]
            nombres += re.findall(r'"username":"([A-Za-z0-9._]{1,40})"', trozo)
    return list(dict.fromkeys(n.lower() for n in nombres))


def _links_from_html(html: str) -> list:
    """Extrae los enlaces externos de los stickers de enlace."""
    urls = []
    for clave in ("story_link_stickers", "link_sticker"):
        for m in re.finditer(rf'"{clave}"', html):
            trozo = html[m.end():m.end() + 1500]
            urls += re.findall(r'"url":"(https?://[^"]{5,300})"', trozo)
    limpios = []
    for u in urls:
        u = u.replace("\\/", "/")
        if "instagram.com" not in u and u not in limpios:
            limpios.append(u)
    return limpios


def _story_id(code: str, media_url: str, pk: str, indice: int) -> str:
    """Identificador **único y estable** por historia.

    El `pk` que aparece en el HTML no cambia al avanzar de historia, así que se
    usaba el mismo id 40 veces y se pisaban entre sí. Se usa el hash del medio,
    que sí es único; si no hay medio, el pk y el índice.
    """
    import hashlib

    if media_url:
        base = hashlib.sha1(media_url.encode("utf-8", "replace")).hexdigest()[:16]
    else:
        base = f"{pk}-{indice}"
    return f"{code}-{base}"


def capture_account(page, ctx, code, real, me, max_stories, media_dir, debug):
    """Recorre las historias de una cuenta y devuelve las capturadas."""
    encontradas = []
    vistos = set()
    page.goto(f"{BASE}/stories/{real}/", wait_until="domcontentloaded")
    time.sleep(5)

    vacios = 0
    for i in range(max_stories):
        try:
            data = page.evaluate(JS_STORY) or {}
        except Exception as exc:  # noqa: BLE001
            print(f"    ⚠ no pude leer la historia: {exc}", file=sys.stderr)
            break

        area = data.get("bestArea") or 0
        media_url = data.get("video") or (data.get("best") if area >= AREA_MINIMA else None)

        if not media_url:
            vacios += 1
            if debug:
                print(f"    (sin medio real: {data.get('total', 0)} imgs, área máx {area})")
            if vacios >= 2:
                break
        else:
            vacios = 0
            html = page.content()
            taken = re.findall(r'"taken_at":(\d{9,11})', html)
            pks = re.findall(r'"pk":"?(\d{15,20})"?', html)
            sid = _story_id(code, media_url, pks[0] if pks else "", i)

            if sid in vistos:
                # La misma historia otra vez: el visor no avanzó. Paramos.
                if debug:
                    print("    (historia repetida: fin del carrusel)")
                break
            vistos.add(sid)

            mentions = _mentions_from_html(html)
            externos = _links_from_html(html)
            kind = "video" if data.get("video") else "image"

            media_path = ""
            if media_dir and media_url:
                ext = ".mp4" if kind == "video" else ".jpg"
                destino = Path(media_dir) / f"{sid}{ext}"   # ← solo códigos
                try:
                    resp = ctx.request.get(media_url, timeout=60000)
                    if resp.ok:
                        destino.parent.mkdir(parents=True, exist_ok=True)
                        destino.write_bytes(resp.body())
                        media_path = str(destino)
                except Exception as exc:  # noqa: BLE001
                    if debug:
                        print(f"    (no pude descargar el medio: {exc})")

            me_key = (me or "").lower()
            encontradas.append({
                "story_id": sid,
                "username": code,
                "pk": sid.split("-", 1)[-1],
                "taken_at": _iso(taken[0]) if taken else datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                "media_url": media_url,
                "media_path": media_path,
                "mentions": mentions,
                "mentions_me": 1 if me_key and me_key in [m.lower() for m in mentions] else 0,
                "links": externos,
                "caption": "",
                # No se guarda la URL: contiene el usuario real. El medio queda en disco.
                "url": "",
            })
            marca = " ⬅️ TE MENCIONA" if (me_key and me_key in [m.lower() for m in mentions]) else ""
            if externos:
                marca += " 🔗"
            print(f"    · historia {len(encontradas)}: {kind} ({area} px²){marca}")

        try:
            page.keyboard.press("ArrowRight")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(random.uniform(1.5, 3.0))

    return encontradas


def main() -> int:
    ap = argparse.ArgumentParser(description="Archivador de historias de Instagram")
    ap.add_argument("--accounts", required=True,
                    help="códigos de cuenta separados por comas (PP,BC,DRZ…)")
    ap.add_argument("--me", default="", help="tu usuario, para detectar menciones")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--out", default="data/story_archive.json")
    ap.add_argument("--media-dir", default="", help="carpeta donde descargar los medios")
    ap.add_argument("--max-stories", type=int, default=25)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("Falta playwright:\n    pip3 install --user playwright\n"
                     "    python3 -m playwright install chromium")

    import config

    pares = []
    for raw in args.accounts.split(","):
        raw = raw.strip()
        if raw:
            pares.append((config.to_code(raw), config.real_username(raw)))
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
        for code, real in pares:
            print(f"→ @{code}")
            try:
                nuevas = capture_account(page, ctx, code, real, me, args.max_stories,
                                         args.media_dir, args.debug)
                todas.extend(nuevas)
                print(f"  {len(nuevas)} historia(s) capturada(s)")
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠ {code}: {exc}", file=sys.stderr)
            # Guardado incremental: si algo falla, lo capturado no se pierde
            try:
                with open(args.out, "w", encoding="utf-8") as fh:
                    json.dump(todas, fh, ensure_ascii=False, indent=1)
            except OSError:
                pass
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
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ no pude guardar en la base: {exc}", file=sys.stderr)
    else:
        print("  No se capturó nada. ¿Tienen historias activas ahora mismo?")
        print("  Consejo: vuelve a intentarlo cuando alguna tenga el aro de historia.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

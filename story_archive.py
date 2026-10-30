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


# JS: enlaces a perfiles DENTRO del visor de la historia (menciones/etiquetas)
JS_MENTION_LINKS = """
() => {
  const re = /^\\/[A-Za-z0-9._]{2,40}\\/$/;
  const media = document.querySelector('video') ||
    Array.from(document.querySelectorAll('img')).find(i => (i.naturalWidth || 0) > 300);
  if (media) {
    let cont = media;
    for (let n = 0; n < 6 && cont; n++) {
      const enlaces = Array.from(cont.querySelectorAll('a[href]'))
        .map(a => a.getAttribute('href')).filter(h => h && re.test(h));
      if (enlaces.length) return enlaces;
      cont = cont.parentElement;
    }
  }
  // Fallback: todo el documento menos header/nav/footer
  const fuera = new Set();
  document.querySelectorAll('header a[href], nav a[href], footer a[href]')
    .forEach(a => fuera.add(a.getAttribute('href')));
  return Array.from(document.querySelectorAll('a[href]'))
    .map(a => a.getAttribute('href'))
    .filter(h => h && re.test(h) && !fuera.has(h));
}
"""


def load_cookies(browser: str, cache: str = "data/cookies.json",
                 max_age_days: float = 7) -> dict:
    """Devuelve las cookies de sesión.

    Primero usa la **caché** (`data/cookies.json`) si es reciente: así la rutina
    automática NO necesita que Brave esté cerrado. Si no hay caché o caducó,
    lee el navegador.
    """
    import time as _t
    cache_p = Path(cache)
    if cache_p.exists():
        try:
            edad = (_t.time() - cache_p.stat().st_mtime) / 86400
            if edad < max_age_days:
                d = json.loads(cache_p.read_text())
                if d.get("sessionid"):
                    print(f"  ✔ Sesión desde caché ({edad:.1f} días)")
                    return d
            else:
                print(f"  (caché de {edad:.0f} días: caducada, leo el navegador)")
        except Exception:
            pass
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


IGNORAR_USUARIOS = {"explore", "blog", "about", "popular", "accounts", "direct",
                    "legal", "privacy", "terms", "help", "api", "web", "home",
                    "search", "notifications", "activity", "instagram", "reels",
                    "stories", "p", "reel", "tv", "emails", "session"}


def _mentions(html: str, dom_links=None, propia: str = "") -> list:
    """Menciones de una historia: JSON embebido + enlaces del visor."""
    nombres = set(_mentions_from_html(html))
    for h in (dom_links or []):
        u = str(h).strip("/").lower()
        if len(u) > 1:
            nombres.add(u)
    propia = (propia or "").lower()
    return [n for n in sorted(nombres)
            if n not in IGNORAR_USUARIOS and n != propia and not n.startswith("_")]


def _arrays_stickers(html: str) -> list:
    """Devuelve el contenido de `story_bloks_stickers` (arrays balanceados).

    Son los stickers PEGADOS sobre la historia. Buscar `ig_mention` suelto por
    todo el HTML da falsos positivos (módulos de sugerencias), así que hay que
    limitarse a este array.
    """
    bloques = []
    for m in re.finditer(r'"story_bloks_stickers"\s*:\s*\[', html):
        ini = m.end() - 1
        prof = 0
        for j in range(ini, min(len(html), ini + 200_000)):
            c = html[j]
            if c == "[":
                prof += 1
            elif c == "]":
                prof -= 1
                if prof == 0:
                    bloques.append(html[ini:j + 1])
                    break
    return bloques


def _mentions_from_html(html: str) -> list:
    """Extrae SOLO las menciones pegadas como sticker en la historia.

    Estructura real de Instagram:
        "story_bloks_stickers": [{
            "bloks_sticker": {"sticker_data": {"ig_mention": {
                "full_name": "...", "username": "..." }}}
        }]
    """
    nombres = []
    for bloque in _arrays_stickers(html):
        for m in re.finditer(
                r'"ig_mention"\s*:\s*\{[^{}]{0,600}?"username"\s*:\s*"([A-Za-z0-9._]{1,40})"',
                bloque):
            nombres.append(m.group(1).lower())

    # Compatibilidad con estructuras antiguas (por si Instagram cambia)
    for clave in ("reel_mentions", "story_mentions"):
        for m in re.finditer(rf'"{clave}"\s*:\s*\[', html):
            trozo = html[m.end():m.end() + 4000]
            nombres += re.findall(r'"username"\s*:\s*"([A-Za-z0-9._]{1,40})"', trozo)

    return list(dict.fromkeys(nombres))


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
        # La URL del CDN lleva firma (?stp=...&oh=...) que cambia en cada carga:
        # se usa solo la ruta para que el id sea ESTABLE entre corridas.
        limpia = str(media_url).split("?")[0]
        base = hashlib.sha1(limpia.encode("utf-8", "replace")).hexdigest()[:16]
    else:
        base = f"{pk}-{indice}"
    return f"{code}-{base}"


def capture_account(page, ctx, code, real, me, max_stories, media_dir, debug, dump=False):
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

            if dump:
                try:
                    d = Path("data/debug")
                    d.mkdir(parents=True, exist_ok=True)
                    (d / f"{code}_{i}.html").write_text(html, encoding="utf-8")
                    print(f"    (HTML guardado: data/debug/{code}_{i}.html)")
                except Exception:
                    pass
            try:
                dom_links = page.evaluate(JS_MENTION_LINKS) or []
            except Exception:
                dom_links = []
            mentions = _mentions(html, dom_links, real)
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
    ap.add_argument("--accounts", default="",
                    help="códigos separados por comas (por defecto: toda la watchlist)")
    ap.add_argument("--me", default="", help="tu usuario, para detectar menciones")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--out", default="data/story_archive.json")
    ap.add_argument("--media-dir", default="", help="carpeta donde descargar los medios")
    ap.add_argument("--max-stories", type=int, default=25)
    ap.add_argument("--save-cookies", action="store_true",
                    help="guarda la sesión en data/cookies.json (así la rutina no necesita Brave cerrado)")
    ap.add_argument("--no-analyze", action="store_true",
                    help="no analizar las imágenes con el modelo local")
    ap.add_argument("--no-me", action="store_true",
                    help="no capturar tus propias historias")
    ap.add_argument("--notify", action="store_true",
                    help="envía el informe diario por Telegram (texto + fotos)")
    ap.add_argument("--notify-photos", type=int, default=3,
                    help="máximo de fotos a enviar (0 = ninguna)")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--dump-html", action="store_true",
                    help="guarda el HTML de cada historia en data/debug/ (para depurar menciones)")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("Falta playwright:\n    pip3 install --user playwright\n"
                     "    python3 -m playwright install chromium")

    import config

    lista = args.accounts or ",".join(config.WATCHLIST)
    # Tus propias historias: también se capturan para ver a quién etiquetas TÚ
    if not args.no_me and config.USERNAME:
        propia = config.to_code(config.USERNAME)
        if propia.lower() not in [x.strip().lower() for x in lista.split(",")]:
            lista = f"{propia},{lista}"
    pares = []
    for raw in lista.split(","):
        raw = raw.strip()
        if raw:
            pares.append((config.to_code(raw), config.real_username(raw)))
    me = (args.me or config.USERNAME or "").strip().lstrip("@").lower()
    if args.save_cookies:
        cookies = load_cookies(args.browser, cache="/dev/null")
        Path("data").mkdir(parents=True, exist_ok=True)
        Path("data/cookies.json").write_text(json.dumps(cookies), encoding="utf-8")
        print(f"✅ Sesión guardada en data/cookies.json ({len(cookies)} cookies)")
        print("   La rutina automática la usará sin necesitar Brave cerrado.")
        return 0

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
        debug_dir = Path("data/debug")
        for code, real in pares:
            print(f"→ @{code}")
            try:
                nuevas = capture_account(page, ctx, code, real, me, args.max_stories,
                                         args.media_dir, args.debug, args.dump_html)
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

            # Análisis LOCAL de las imágenes (nada sale de tu Mac)
            if not args.no_analyze:
                try:
                    import vision
                    if vision.disponible() or vision.asegurar_servicio():
                        pendientes = [s for s in todas
                                      if s.get("kind") == "image" and s.get("media_path")]
                        if pendientes:
                            print(f"  → Analizando {len(pendientes)} imagen(es) con {vision.MODELO}…")
                        for s in pendientes:
                            desc = vision.describe(s["media_path"])
                            if desc:
                                storage.set_story_description(s["story_id"], desc)
                                s["description"] = desc
                                print(f"    · {s.get('username')}: {desc}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ⚠ análisis local: {exc}", file=sys.stderr)
            print(f"→ Guardadas en la base: {n}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ no pude guardar en la base: {exc}", file=sys.stderr)
    else:
        print("  No se capturó nada. ¿Tienen historias activas ahora mismo?")

    # Informe diario por Telegram (texto + fotos de las historias)
    if args.notify:
        try:
            import notify

            # 🚨 Alerta URGENTE aparte si alguien te etiquetó
            tocados = [s for s in todas if s.get("mentions_me")]
            if tocados:
                aviso = "🚨 ¡TE ETIQUETARON EN UNA HISTORIA!\n\n"
                for s in tocados:
                    aviso += (f"· {s.get('username')} — "
                              f"{str(s.get('taken_at'))[:16]}\n")
                notify.send_telegram(aviso)
                print(f"→ Alerta de etiqueta: {len(tocados)}")

            dia = datetime.now().strftime("%d %b %Y")
            mensaje = notify.build_stories_report(todas, dia)
            ok, info = notify.send_telegram(mensaje)
            print(f"→ Telegram: {'✅ enviado' if ok else '⚠️ ' + info}")
            if ok and args.notify_photos:
                fotos = [s for s in todas
                         if s.get("media_path") and s.get("kind") == "image"]
                for s in fotos[:args.notify_photos]:
                    cap = (f"@{s.get('username')} · {str(s.get('taken_at'))[:16]}"
                           + (" · ⬅️ TE MENCIONA" if s.get("mentions_me") else ""))
                    ok2, info2 = notify.send_telegram_photo(s["media_path"], cap)
                    print(f"   · foto de {s.get('username')}: "
                          f"{'✅' if ok2 else '⚠️ ' + info2}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ no se pudo enviar el informe: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Variante "humana": abre el perfil en un navegador real, hace CLIC en
"seguidos/seguidores" y hace SCROLL leyendo los nombres de la pantalla.

Sin llamadas a la API interna → evita el HTTP 429.

⚠️ Va contra los ToS de Instagram. Riesgo para la cuenta burner. Ritmo lento.

Instalación (una vez):
    pip3 install --user playwright browser_cookie3
    python3 -m playwright install chromium

Uso (cierra Brave antes):
    python3 burner_human.py --username TU_USUARIO --debug
    python3 burner_human.py --username TU_USUARIO --followers-limit 300
"""
import argparse
import json
import random
import sys
import time

BASE = "https://www.instagram.com"
DIALOG = 'div[role="dialog"], [role="dialog"]'


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
        raise SystemExit("No encontré 'sessionid'. ¿Cerraste el navegador y autorizaste el Llavero?")
    print(f"  ✔ Sesión encontrada (usuario id {cookies.get('ds_user_id', '?')})")
    return cookies


# JS: extrae los usernames visibles dentro del modal
JS_READ = """
() => {
  const dlg = document.querySelector('div[role="dialog"]') || document.querySelector('[role="dialog"]');
  if (!dlg) return [];
  return Array.from(dlg.querySelectorAll('a[href]'))
    .map(a => a.getAttribute('href'))
    .filter(h => h && h.startsWith('/') && h.split('/').filter(Boolean).length === 1)
    .map(h => h.split('/').filter(Boolean)[0]);
}
"""

# JS: baja el scroll del modal hasta el final
JS_SCROLL = """
() => {
  const dlg = document.querySelector('div[role="dialog"]') || document.querySelector('[role="dialog"]');
  if (!dlg) return false;
  const cands = Array.from(dlg.querySelectorAll('div'))
    .filter(e => e.scrollHeight > e.clientHeight + 40);
  if (!cands.length) return false;
  const sc = cands[cands.length - 1];
  sc.scrollTop = sc.scrollHeight;
  return true;
}
"""

# JS: diagnóstico de la página
JS_DIAG = """
() => ({
  title: document.title,
  url: location.href,
  links_following: document.querySelectorAll('a[href*="/following/"]').length,
  links_followers: document.querySelectorAll('a[href*="/followers/"]').length,
  has_dialog: !!document.querySelector('div[role="dialog"], [role="dialog"]'),
  body_chars: document.body ? document.body.innerText.length : 0,
})
"""


def open_list(page, username: str, kind: str, debug: bool = False) -> bool:
    """Abre la lista de 'following'/'followers' con 3 estrategias + fallback."""
    # Estrategia 1: clic en el enlace del perfil
    for sel in (f'a[href="/{username}/{kind}/"]', f'a[href$="/{kind}/"]',
                f'a[href*="/{kind}/"]'):
        try:
            loc = page.locator(sel).first
            loc.scroll_into_view_if_needed(timeout=4000)
            loc.click(timeout=6000)
            page.wait_for_selector(DIALOG, timeout=12000, state="attached")
            time.sleep(2)
            if debug:
                print(f"    (abierto por selector: {sel})")
            return True
        except Exception:
            continue

    # Estrategia 2: navegar directamente a la URL de la lista
    try:
        if debug:
            print(f"    (intentando URL directa /{username}/{kind}/)")
        page.goto(f"{BASE}/{username}/{kind}/", wait_until="domcontentloaded")
        page.wait_for_selector(DIALOG, timeout=15000, state="attached")
        time.sleep(2)
        return True
    except Exception as exc:
        if debug:
            print(f"    (URL directa falló: {type(exc).__name__})")
    return False


def collect(page, limit: int, max_scrolls: int) -> list:
    names, stall = set(), 0
    for _ in range(max_scrolls):
        try:
            names.update(n for n in page.evaluate(JS_READ) if n)
        except Exception:
            pass
        print(f"    {len(names)} cuentas…", end="\r", flush=True)
        if limit and len(names) >= limit:
            break
        before = len(names)
        try:
            page.evaluate(JS_SCROLL)
        except Exception:
            pass
        time.sleep(random.uniform(1.2, 2.2))
        try:
            names.update(n for n in page.evaluate(JS_READ) if n)
        except Exception:
            pass
        if len(names) == before:
            stall += 1
            if stall >= 5:
                break
        else:
            stall = 0
    print(f"    ✔ {len(names)} cuentas          ")
    return sorted(names)


def main() -> int:
    ap = argparse.ArgumentParser(description="Scraper 'humano' con clic + scroll")
    ap.add_argument("--username", required=True, help="perfil objetivo (tu cuenta, sin @)")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--out", default="burner_snapshot.json")
    ap.add_argument("--stories-out", default="burner_stories.json")
    ap.add_argument("--following-limit", type=int, default=0)
    ap.add_argument("--followers-limit", type=int, default=300)
    ap.add_argument("--max-scrolls", type=int, default=400)
    ap.add_argument("--watchlist", default="")
    ap.add_argument("--wait", type=float, default=4.0, help="espera tras cargar el perfil")
    ap.add_argument("--dump-html", action="store_true", help="guarda el HTML para depurar")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--no-stories", action="store_true", help="no mirar historias")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Falta playwright:\n"
            "    pip3 install --user playwright\n"
            "    python3 -m playwright install chromium")

    target = args.username.strip().lstrip("@")
    watch = [] if args.no_stories else [
        u.strip().lstrip("@") for u in args.watchlist.split(",") if u.strip()]
    cookies = load_cookies(args.browser)
    pw_cookies = [{"name": k, "value": v, "domain": ".instagram.com", "path": "/"}
                  for k, v in cookies.items()]

    print("=" * 62)
    print("  Método HUMANO (clic + scroll). ⚠️  ToS + riesgo para la burner.")
    print("=" * 62)

    following, followers, story_mentions = [], [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(locale="es-ES", viewport={"width": 1280, "height": 900})
        ctx.add_cookies(pw_cookies)
        page = ctx.new_page()

        print(f"→ Abriendo instagram.com/{target}/ …")
        page.goto(f"{BASE}/{target}/", wait_until="domcontentloaded")
        time.sleep(args.wait)

        if args.debug or args.dump_html:
            try:
                diag = page.evaluate(JS_DIAG)
                print("  · DIAGNÓSTICO:", json.dumps(diag, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001
                print(f"  · diagnóstico falló: {exc}")
        if args.dump_html:
            with open("burner_profile.html", "w", encoding="utf-8") as fh:
                fh.write(page.content())
            print("  · HTML guardado en burner_profile.html")

        print("→ Leyendo SEGUIDOS…")
        if open_list(page, target, "following", args.debug):
            following = collect(page, args.following_limit, args.max_scrolls)
            page.keyboard.press("Escape")
            time.sleep(2)
        else:
            print("  ⚠ no se pudo abrir la lista de seguidos", file=sys.stderr)

        print("→ Leyendo SEGUIDORES…")
        if open_list(page, target, "followers", args.debug):
            followers = collect(page, args.followers_limit, args.max_scrolls)
            page.keyboard.press("Escape")
            time.sleep(2)
        else:
            print("  ⚠ no se pudo abrir la lista de seguidores", file=sys.stderr)

        if watch:
            print("→ Mirando historias de la watchlist…")
            me = target.lower()
            for account in watch:
                try:
                    page.goto(f"{BASE}/stories/{account}/", wait_until="domcontentloaded")
                    time.sleep(4)
                    found = page.evaluate(
                        """() => Array.from(document.querySelectorAll('a[href^="/"]'))
                                 .map(a => a.getAttribute('href'))
                                 .filter(h => /^\\/[A-Za-z0-9._]+\\/$/.test(h))
                                 .map(h => h.split('/')[1].toLowerCase())""")
                    hits = sorted(set(found) & {me})
                    pk = page.url.rstrip("/").split("/")[-1]
                    for _ in hits:
                        story_mentions.append({
                            "id": f"{account}-{pk}-{me}",
                            "source_username": account.lower(),
                            "mentioned_username": me,
                            "direction": "them_to_me",
                            "url": page.url,
                            "timestamp": int(time.time()),
                        })
                    print(f"  @{account}: {'TE MENCIONA ✅' if hits else 'sin mención tuya'}"
                          + (f" ({len(found)} cuentas vistas)" if args.debug else ""))
                    time.sleep(random.uniform(2, 4))
                except Exception as exc:  # noqa: BLE001
                    print(f"  ⚠ @{account}: {exc}", file=sys.stderr)

        browser.close()

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"username": target, "ts": int(time.time() * 1000),
                   "followers": followers, "following": following}, fh, ensure_ascii=False)
    print(f"\n→ Guardado {args.out}: {len(followers)} seguidores, {len(following)} seguidos")

    if watch:
        with open(args.stories_out, "w", encoding="utf-8") as fh:
            json.dump(story_mentions, fh, ensure_ascii=False)
        print(f"→ Guardado {args.stories_out}: {len(story_mentions)} menciones en historias")

    if not followers and not following:
        print("\n⚠ No se leyó ninguna cuenta. Reintenta añadiendo:  --debug --dump-html")
    else:
        print("\n✔ Listo. Súbelos al panel:")
        print(f"   · {args.out}          → 📥 Importar snapshot histórico")
        print(f"   · {args.stories_out}  → 📥 Importar menciones de historias")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

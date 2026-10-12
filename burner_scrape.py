"""Scraper LOCAL que usa la sesión de tu cuenta burner (navegador Brave).

⚠️ AVISO IMPORTANTE
   Esto va CONTRA los términos de uso de Instagram y puede provocar bloqueos o
   restricciones de la cuenta burner. Úsalo con ritmo lento, poco volumen y
   bajo tu responsabilidad. El script solo lee datos públicos del perfil que
   indiques, pero lo hace con una sesión iniciada.

Qué obtiene
   1) Lista de seguidos y seguidores del perfil objetivo (tu cuenta).
      → Se guarda en formato "snapshot", el MISMO que ya importa el panel.
   2) Menciones en historias de las cuentas de tu watchlist.
      → Se guarda en el formato que importa el panel en "Importar historias".

Cómo usarlo
   pip3 install --user requests browser_cookie3
   # Cierra Brave antes de ejecutar
   python3 burner_scrape.py --username TU_USUARIO --debug

Si sale HTTP 429
   Instagram está limitando. Espera 20-30 min, sube --delay y reduce el volumen.
   El script reintenta solo con espera creciente.
"""
import argparse
import json
import random
import sys
import time

BASE = "https://www.instagram.com"
APP_ID = "936619743392459"       # x-ig-app-id público de la web
ASBD_ID = "129477"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def load_cookies(browser: str) -> dict:
    try:
        import browser_cookie3
    except ImportError:
        raise SystemExit(
            "Falta browser_cookie3. Instálalo con:\n"
            "    pip3 install --user requests browser_cookie3"
        )
    fn = getattr(browser_cookie3, browser, None)
    if fn is None:
        raise SystemExit(f"Navegador no soportado: {browser}")
    print(f"→ Leyendo cookies de {browser}…")
    jar = fn(domain_name="instagram.com")
    cookies = {c.name: c.value for c in jar}
    if "sessionid" not in cookies:
        raise SystemExit(
            "No encontré la cookie 'sessionid'. Comprueba que:\n"
            "  1) La burner está logueada en instagram.com en ese navegador.\n"
            "  2) Cerraste el navegador antes de ejecutar.\n"
            "  3) Autorizaste el acceso al Llavero si macOS lo pidió."
        )
    print(f"  ✔ Sesión encontrada (usuario id {cookies.get('ds_user_id', '?')})")
    return cookies


def build_session(cookies: dict):
    import requests
    s = requests.Session()
    s.cookies.update(cookies)
    s.headers.update({
        "user-agent": UA,
        "accept": "*/*",
        "accept-language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
        "x-ig-app-id": APP_ID,
        "x-asbd-id": ASBD_ID,
        "x-ig-www-claim": "0",
        "x-csrftoken": cookies.get("csrftoken", ""),
        "x-requested-with": "XMLHttpRequest",
        "origin": BASE,
        "referer": BASE + "/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    })
    return s


def _get(session, url: str, debug: bool = False, tries: int = 4):
    """GET con reintentos y espera creciente ante 429/5xx."""
    r = None
    for attempt in range(tries):
        r = session.get(url, timeout=30)
        if debug:
            print(f"  · GET {url.split('?')[0]} → HTTP {r.status_code}")
            if r.status_code != 200:
                print(f"    respuesta: {r.text[:300].replace(chr(10), ' ')}")
        if r.status_code in (429, 500, 502, 503):
            wait = 25 * (attempt + 1)
            print(f"  ⏳ HTTP {r.status_code}: esperando {wait}s y reintentando…",
                  file=sys.stderr)
            time.sleep(wait)
            continue
        return r
    return r


def get_user_id(session, username: str, debug: bool = False) -> str:
    r = _get(session, f"{BASE}/api/v1/users/web_profile_info/?username={username}", debug=debug)
    if r is None or r.status_code != 200:
        code = r.status_code if r is not None else "?"
        if code == 429:
            raise SystemExit(
                "Instagram devolvió 429 (límite de peticiones).\n"
                "→ Espera 20-30 minutos y vuelve a intentarlo.\n"
                "→ Si persiste, la burner es demasiado nueva/limitada: usa la variante Playwright."
            )
        raise SystemExit(f"No pude resolver @{username} (HTTP {code}).")
    user = (r.json().get("data") or {}).get("user") or {}
    uid = user.get("id")
    if not uid:
        raise SystemExit(f"@{username} no devolvió id (¿privado o bloqueado?)")
    print(f"  ✔ @{username} → id {uid}")
    return str(uid)


def fetch_list(session, user_id: str, kind: str, limit: int = 0,
               delay=(1.5, 3.0), debug: bool = False) -> list:
    out, seen, max_id, page = [], set(), "", 0
    while True:
        url = f"{BASE}/api/v1/friendships/{user_id}/{kind}/?count=24"
        if max_id:
            url += f"&max_id={max_id}"
        r = _get(session, url, debug=debug)
        if r is None or r.status_code != 200:
            print(f"  ⚠ {kind}: HTTP {r.status_code if r is not None else '?'} — "
                  f"{(r.text[:160] if r is not None else '')}", file=sys.stderr)
            break
        data = r.json()
        for u in data.get("users") or []:
            name = u.get("username")
            if name and name.lower() not in seen:
                seen.add(name.lower())
                out.append(name)
        page += 1
        print(f"  {kind}: {len(out)} (página {page})", end="\r", flush=True)
        max_id = data.get("next_max_id")
        if not max_id or (limit and len(out) >= limit):
            break
        time.sleep(random.uniform(*delay))
    print(f"  ✔ {kind}: {len(out)} cuentas           ")
    return out


def fetch_stories(session, user_id: str, debug: bool = False) -> list:
    r = _get(session, f"{BASE}/api/v1/feed/reels_media/?reel_ids={user_id}", debug=debug)
    if r is None or r.status_code != 200:
        return []
    items = []
    for reel in (r.json().get("reels") or {}).values():
        owner = ((reel.get("user") or {}).get("username") or "").lower()
        for item in reel.get("items") or []:
            mentions = []
            for key in ("reel_mentions", "story_mentions"):
                for m in item.get(key) or []:
                    u = ((m.get("user") or {}).get("username") or "").strip().lstrip("@")
                    if u:
                        mentions.append(u.lower())
            pk = item.get("pk") or item.get("id")
            items.append({
                "id": str(pk),
                "source_username": owner,
                "mentions": sorted(set(mentions)),
                "timestamp": item.get("taken_at"),
                "url": f"{BASE}/stories/{owner}/{pk}/",
            })
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description="Scraper local con la sesión de la burner")
    ap.add_argument("--username", required=True, help="perfil objetivo (tu cuenta, sin @)")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--out", default="burner_snapshot.json")
    ap.add_argument("--stories-out", default="burner_stories.json")
    ap.add_argument("--following-limit", type=int, default=0, help="0 = sin límite")
    ap.add_argument("--followers-limit", type=int, default=0, help="0 = sin límite (¡puede ser enorme!)")
    ap.add_argument("--watchlist", default="")
    ap.add_argument("--delay", type=float, default=1.5, help="segundos base entre páginas")
    ap.add_argument("--no-lists", action="store_true", help="solo historias")
    ap.add_argument("--debug", action="store_true", help="muestra cada petición y su respuesta")
    args = ap.parse_args()

    print("=" * 62)
    print("  Scraper LOCAL con sesión de la burner")
    print("  ⚠️  Va contra los ToS de Instagram. Riesgo para la burner.")
    print("=" * 62)

    cookies = load_cookies(args.browser)
    session = build_session(cookies)
    delay = (args.delay, args.delay + 1.5)

    target = args.username.strip().lstrip("@")
    following, followers = [], []
    if not args.no_lists:
        uid = get_user_id(session, target, debug=args.debug)
        print("→ Descargando seguidos…")
        following = fetch_list(session, uid, "following", args.following_limit,
                               delay=delay, debug=args.debug)
        print("→ Descargando seguidores…")
        followers = fetch_list(session, uid, "followers", args.followers_limit,
                               delay=delay, debug=args.debug)
        payload = {
            "username": target, "userId": uid,
            "ts": int(time.time() * 1000),
            "followers": followers, "following": following,
        }
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        print(f"→ Guardado {args.out}: {len(followers)} seguidores, {len(following)} seguidos")

    watch = [u.strip().lstrip("@") for u in args.watchlist.split(",") if u.strip()]
    if watch:
        print("→ Mirando historias de la watchlist…")
        me = target.lower()
        story_mentions = []
        for account in watch:
            try:
                auid = get_user_id(session, account, debug=args.debug)
            except SystemExit as exc:
                print(f"  ⚠ {account}: {exc}", file=sys.stderr)
                continue
            stories = fetch_stories(session, auid, debug=args.debug)
            hits = 0
            for st in stories:
                for mentioned in st["mentions"]:
                    if mentioned == me:
                        story_mentions.append({
                            "id": f"{st['id']}-{mentioned}",
                            "source_username": st["source_username"],
                            "mentioned_username": mentioned,
                            "direction": "them_to_me",
                            "url": st["url"],
                            "timestamp": st["timestamp"],
                        })
                        hits += 1
            print(f"  @{account}: {len(stories)} historias, {hits} te mencionan")
            time.sleep(random.uniform(*delay))
        with open(args.stories_out, "w", encoding="utf-8") as fh:
            json.dump(story_mentions, fh, ensure_ascii=False)
        print(f"→ Guardado {args.stories_out}: {len(story_mentions)} menciones")

    print("\n✔ Listo. Sube los JSON al panel:")
    print(f"   · {args.out}          → 📥 Importar snapshot histórico")
    print(f"   · {args.stories_out}  → 📥 Importar menciones de historias")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

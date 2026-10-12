"""Scraper LOCAL que usa la sesión de tu cuenta burner (navegador Brave).

⚠️ AVISO IMPORTANTE
   Esto va CONTRA los términos de uso de Instagram y puede provocar bloqueos o
   restricciones de la cuenta burner. Úsalo con ritmo lento, poco volumen y
   bajo tu responsabilidad. El script solo lee datos públicos del perfil que
   indiques, pero lo hace con una sesión iniciada.

Qué obtiene
   1) Lista de seguidos y seguidores del perfil objetivo (tu cuenta).
      → Se guarda en formato "snapshot", el MISMO que ya importa el panel.
   2) Menciones en historias de las cuentas de tu watchlist (si las sigues con
      la burner y tienen historias activas).
      → Se guarda en el formato que importa el panel en "Importar historias".

Cómo usarlo
   pip install requests browser_cookie3
   # Cierra Brave antes de ejecutar (para que las cookies no estén bloqueadas)
   python burner_scrape.py --username TU_USUARIO --watchlist PP,BC

   Al terminar tendrás:
     - burner_snapshot.json   → súbelo en "📥 Importar snapshot histórico"
     - burner_stories.json    → súbelo en "📥 Importar menciones de historias"
"""
import argparse
import json
import random
import sys
import time

BASE = "https://www.instagram.com"
APP_ID = "936619743392459"  # x-ig-app-id público de la web de Instagram
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def load_cookies(browser: str) -> dict:
    """Lee las cookies de Instagram del navegador indicado."""
    try:
        import browser_cookie3
    except ImportError:
        raise SystemExit(
            "Falta browser_cookie3. Instálalo con:\n    pip install requests browser_cookie3"
        )
    fn = getattr(browser_cookie3, browser, None)
    if fn is None:
        raise SystemExit(f"Navegador no soportado: {browser} (usa: brave, chrome, chromium, edge, firefox)")
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
        "x-ig-app-id": APP_ID,
        "x-csrftoken": cookies.get("csrftoken", ""),
        "x-requested-with": "XMLHttpRequest",
        "referer": BASE + "/",
        "accept": "*/*",
    })
    return s


def get_user_id(session, username: str) -> str:
    r = session.get(f"{BASE}/api/v1/users/web_profile_info/?username={username}", timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"No pude resolver @{username} (HTTP {r.status_code}). ¿Existe esa cuenta?")
    user = (r.json().get("data") or {}).get("user") or {}
    uid = user.get("id")
    if not uid:
        raise SystemExit(f"@{username} no devolvió id (¿perfil privado o bloqueado?)")
    print(f"  ✔ @{username} → id {uid}")
    return str(uid)


def fetch_list(session, user_id: str, kind: str, limit: int = 0,
               delay=(1.0, 2.2)) -> list:
    """Descarga 'following' o 'followers' paginando con ritmo humano."""
    out, seen, max_id, page = [], set(), "", 0
    while True:
        url = f"{BASE}/api/v1/friendships/{user_id}/{kind}/?count=24"
        if max_id:
            url += f"&max_id={max_id}"
        r = session.get(url, timeout=30)
        if r.status_code != 200:
            print(f"  ⚠ {kind}: HTTP {r.status_code} — {r.text[:160]}", file=sys.stderr)
            break
        data = r.json()
        users = data.get("users") or []
        for u in users:
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


def fetch_stories(session, user_id: str) -> list:
    """Historias activas de una cuenta (si la sesión puede verlas)."""
    r = session.get(f"{BASE}/api/v1/feed/reels_media/?reel_ids={user_id}", timeout=30)
    if r.status_code != 200:
        return []
    data = r.json()
    items = []
    for reel in (data.get("reels") or {}).values():
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
    ap.add_argument("--browser", default="brave", help="brave | chrome | chromium | edge | firefox")
    ap.add_argument("--out", default="burner_snapshot.json")
    ap.add_argument("--stories-out", default="burner_stories.json")
    ap.add_argument("--following-limit", type=int, default=0, help="0 = sin límite")
    ap.add_argument("--followers-limit", type=int, default=0, help="0 = sin límite (¡puede ser enorme!)")
    ap.add_argument("--watchlist", default="", help="cuentas separadas por comas para mirar historias")
    ap.add_argument("--no-lists", action="store_true", help="solo historias, sin listas")
    args = ap.parse_args()

    print("=" * 62)
    print("  Scraper LOCAL con sesión de la burner")
    print("  ⚠️  Va contra los ToS de Instagram. Riesgo para la burner.")
    print("=" * 62)

    cookies = load_cookies(args.browser)
    session = build_session(cookies)

    target = args.username.strip().lstrip("@")
    following, followers = [], []
    if not args.no_lists:
        uid = get_user_id(session, target)
        print("→ Descargando seguidos…")
        following = fetch_list(session, uid, "following", args.following_limit)
        print("→ Descargando seguidores…")
        followers = fetch_list(session, uid, "followers", args.followers_limit)
        payload = {
            "username": target,
            "userId": uid,
            "ts": int(time.time() * 1000),
            "followers": followers,
            "following": following,
        }
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        print(f"→ Guardado {args.out}: {len(followers)} seguidores, {len(following)} seguidos")

    # --- Historias de la watchlist ---
    watch = [u.strip().lstrip("@") for u in args.watchlist.split(",") if u.strip()]
    if watch:
        print("→ Mirando historias de la watchlist…")
        me = target.lower()
        story_mentions = []
        for account in watch:
            try:
                auid = get_user_id(session, account)
            except SystemExit as exc:
                print(f"  ⚠ {account}: {exc}", file=sys.stderr)
                continue
            stories = fetch_stories(session, auid)
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
            time.sleep(random.uniform(1.0, 2.0))
        with open(args.stories_out, "w", encoding="utf-8") as fh:
            json.dump(story_mentions, fh, ensure_ascii=False)
        print(f"→ Guardado {args.stories_out}: {len(story_mentions)} menciones")

    print("\n✔ Listo. Sube los JSON al panel:")
    print(f"   · {args.out}          → ⭐ Cuentas destacadas → 📥 Importar snapshot histórico")
    print(f"   · {args.stories_out}  → ⭐ Cuentas destacadas → 📥 Importar menciones de historias")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

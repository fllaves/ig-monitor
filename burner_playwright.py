"""Variante ROBUSTA: hace las peticiones desde un navegador real (Playwright).

Por qué existe: Instagram devolvía HTTP 429 al usar `requests` (detecta que no
es un navegador). Aquí lanzamos Chromium de verdad, le inyectamos las cookies de
tu sesión de Brave y hacemos `fetch()` DESDE la propia página de Instagram, así
que la petición sale con huella de navegador real.

⚠️ Va contra los ToS de Instagram. Riesgo para la cuenta burner. Ritmo lento.

Instalación (una vez):
    pip3 install --user playwright browser_cookie3
    python3 -m playwright install chromium

Uso:
    # cierra Brave antes
    python3 burner_playwright.py --username TU_USUARIO \
        --watchlist PP,BC,F,JU,DRZ
"""
import argparse
import json
import random
import sys
import time

BASE = "https://www.instagram.com"
APP_ID = "936619743392459"


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
    importantes = ["sessionid", "csrftoken", "ds_user_id", "mid", "ig_did", "rur"]
    print("  · Cookies clave: " + ", ".join(
        f"{k}={'✅' if k in cookies else '❌'}" for k in importantes))
    print(f"  · Longitud de sessionid: {len(cookies.get('sessionid', ''))}")
    return cookies


def main() -> int:
    ap = argparse.ArgumentParser(description="Scraper con navegador real (Playwright)")
    ap.add_argument("--username", required=True, help="perfil objetivo (tu cuenta, sin @)")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--out", default="burner_snapshot.json")
    ap.add_argument("--stories-out", default="burner_stories.json")
    ap.add_argument("--following-limit", type=int, default=0)
    ap.add_argument("--followers-limit", type=int, default=0)
    ap.add_argument("--watchlist", default="")
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--headless", action="store_true", help="sin ventana visible (más detectable)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Falta playwright. Instálalo con:\n"
            "    pip3 install --user playwright\n"
            "    python3 -m playwright install chromium"
        )

    cookies = load_cookies(args.browser)
    pw_cookies = [{"name": k, "value": v, "domain": ".instagram.com", "path": "/"}
                  for k, v in cookies.items()]

    target = args.username.strip().lstrip("@")
    watch = [u.strip().lstrip("@") for u in args.watchlist.split(",") if u.strip()]
    following, followers, story_mentions = [], [], []

    print("→ Abriendo navegador real…")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        ctx = browser.new_context(locale="es-ES")
        ctx.add_cookies(pw_cookies)
        page = ctx.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded")
        time.sleep(2)

        def api(path: str):
            """Hace fetch() DESDE la página real de Instagram."""
            res = page.evaluate(
                """async (url) => {
                    const r = await fetch(url, {
                        headers: {"x-ig-app-id": "936619743392459"},
                        credentials: "include"
                    });
                    return {status: r.status, body: await r.text()};
                }""",
                BASE + path,
            )
            if args.debug:
                print(f"  · {path.split('?')[0]} → HTTP {res['status']}")
            return res

        def user_id(username: str) -> str:
            res = api(f"/api/v1/users/web_profile_info/?username={username}")
            if res["status"] != 200:
                raise SystemExit(f"No pude resolver @{username} (HTTP {res['status']}).")
            user = (json.loads(res["body"]).get("data") or {}).get("user") or {}
            uid = user.get("id")
            if not uid:
                raise SystemExit(f"@{username} sin id (¿privado/bloqueado?).")
            print(f"  ✔ @{username} → id {uid}")
            return str(uid)

        def fetch_list(uid: str, kind: str, limit: int) -> list:
            out, seen, max_id, errors = [], set(), "", 0
            while True:
                path = f"/api/v1/friendships/{uid}/{kind}/?count=24"
                if max_id:
                    path += f"&max_id={max_id}"
                res = api(path)
                if res["status"] != 200:
                    errors += 1
                    print(f"  ⚠ {kind}: HTTP {res['status']}", file=sys.stderr)
                    if errors >= 3:
                        break
                    time.sleep(30)
                    continue
                errors = 0
                data = json.loads(res["body"])
                for u in data.get("users") or []:
                    name = u.get("username")
                    if name and name.lower() not in seen:
                        seen.add(name.lower())
                        out.append(name)
                print(f"  {kind}: {len(out)}", end="\r", flush=True)
                max_id = data.get("next_max_id")
                if not max_id or (limit and len(out) >= limit):
                    break
                time.sleep(random.uniform(args.delay, args.delay + 1.5))
            print(f"  ✔ {kind}: {len(out)} cuentas           ")
            return out

        if not watch and args.following_limit == 0 and args.followers_limit == 0:
            args.followers_limit = 200  # salvavidas por defecto

        uid = user_id(target)
        print("→ Descargando seguidos…")
        following = fetch_list(uid, "following", args.following_limit)
        print("→ Descargando seguidores…")
        followers = fetch_list(uid, "followers", args.followers_limit)

        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"username": target, "userId": uid, "ts": int(time.time() * 1000),
                       "followers": followers, "following": following}, fh, ensure_ascii=False)
        print(f"→ Guardado {args.out}: {len(followers)} seguidores, {len(following)} seguidos")

        if watch:
            print("→ Mirando historias de la watchlist…")
            me = target.lower()
            for account in watch:
                try:
                    auid = user_id(account)
                except SystemExit as exc:
                    print(f"  ⚠ {account}: {exc}", file=sys.stderr)
                    continue
                res = api(f"/api/v1/feed/reels_media/?reel_ids={auid}")
                if res["status"] != 200:
                    print(f"  ⚠ @{account}: historias HTTP {res['status']}", file=sys.stderr)
                    continue
                reels = json.loads(res["body"]).get("reels") or {}
                hits, total = 0, 0
                for reel in reels.values():
                    owner = ((reel.get("user") or {}).get("username") or account).lower()
                    for item in reel.get("items") or []:
                        total += 1
                        mentioned = set()
                        for key in ("reel_mentions", "story_mentions"):
                            for m in item.get(key) or []:
                                u = ((m.get("user") or {}).get("username") or "").strip().lstrip("@")
                                if u:
                                    mentioned.add(u.lower())
                        if me in mentioned:
                            pk = item.get("pk") or item.get("id")
                            story_mentions.append({
                                "id": f"{pk}-{me}",
                                "source_username": owner,
                                "mentioned_username": me,
                                "direction": "them_to_me",
                                "url": f"{BASE}/stories/{owner}/{pk}/",
                                "timestamp": item.get("taken_at"),
                            })
                            hits += 1
                print(f"  @{account}: {total} historias, {hits} te mencionan")
                time.sleep(random.uniform(args.delay, args.delay + 1.5))

        browser.close()

    if watch:
        with open(args.stories_out, "w", encoding="utf-8") as fh:
            json.dump(story_mentions, fh, ensure_ascii=False)
        print(f"→ Guardado {args.stories_out}: {len(story_mentions)} menciones")

    print("\n✔ Listo. Sube los JSON al panel:")
    print(f"   · {args.out}          → 📥 Importar snapshot histórico")
    print(f"   · {args.stories_out}  → 📥 Importar menciones de historias")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

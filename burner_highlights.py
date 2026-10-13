"""Escáner de DESTACADAS: busca menciones tuyas en las historias destacadas.

Las historias normales desaparecen a las 24 h, pero si alguien guardó una en una
"destacada", esa historia es PÚBLICA, PERMANENTE y conserva su FECHA ORIGINAL.
Es el único lugar donde una mención de historia puede seguir viva.

Usa un navegador real (Playwright) con la sesión de tu cuenta burner.

⚠️ Va contra los ToS de Instagram. Riesgo para la cuenta burner. Ritmo lento.

Instalación (una vez):
    pip3 install --user playwright browser_cookie3
    python3 -m playwright install chromium

Uso (cierra Brave antes):
    python3 burner_highlights.py --me TU_USUARIO --accounts PP,BC
    python3 burner_highlights.py --me TU_USUARIO --accounts TU_USUARIO,otra  # incluye las tuyas
"""
import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timezone

BASE = "https://www.instagram.com"

JS_HIGHLIGHTS = """
() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="/stories/highlights/"]').forEach(a => {
    const m = (a.getAttribute('href') || '').match(/highlights\\/(\\d+)/);
    if (m && !seen.has(m[1])) {
      seen.add(m[1]);
      out.push({ id: m[1], name: (a.innerText || '').trim().slice(0, 40) });
    }
  });
  return out;
}
"""

JS_MENTIONS = """
() => {
  const names = new Set();
  document.querySelectorAll('a[href^="/"]').forEach(a => {
    const h = a.getAttribute('href') || '';
    if (/^\\/[A-Za-z0-9._]+\\/$/.test(h)) names.add(h.split('/')[1].toLowerCase());
  });
  return Array.from(names);
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


def to_iso(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def scan_account(page, account: str, terms: list, wait: float, debug: bool) -> list:
    """Devuelve las menciones encontradas en las destacadas de `account`."""
    found = []
    print(f"→ @{account}")
    page.goto(f"{BASE}/{account}/", wait_until="domcontentloaded")
    time.sleep(wait)

    try:
        highlights = page.evaluate(JS_HIGHLIGHTS) or []
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ no pude leer las destacadas: {exc}", file=sys.stderr)
        return found

    if not highlights:
        print("  · sin destacadas (o no cargaron)")
        return found

    print(f"  · {len(highlights)} destacadas encontradas")
    for h in highlights:
        url = f"{BASE}/stories/highlights/{h['id']}/"
        try:
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(max(2.0, wait - 1))
            html = page.content()
            low = html.lower()
            matched = [t for t in terms if t in low]
            if matched:
                taken = [to_iso(t) for t in re.findall(r'"taken_at":(\d+)', html)]
                taken = sorted({t for t in taken if t})
                for term in matched:
                    found.append({
                        "id": f"{account}-{h['id']}-{term}",
                        "source_username": account.lower(),
                        "mentioned_username": term,
                        "direction": ("me_to_them" if account.lower() == term else "them_to_me"),
                        "url": url,
                        "highlight": h.get("name") or "",
                        "timestamp": taken[0] if taken else "",
                        "dates": taken,
                    })
                print(f"    ✅ DESTACADA «{h.get('name') or h['id']}» menciona: "
                      f"{', '.join(matched)}" + (f" ({taken[0][:10]})" if taken else ""))
            elif debug:
                print(f"    · «{h.get('name') or h['id']}»: sin mención")
        except Exception as exc:  # noqa: BLE001
            print(f"    ⚠ destacada {h['id']}: {exc}", file=sys.stderr)
        time.sleep(random.uniform(1.5, 3.0))

    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="Escáner de historias destacadas")
    ap.add_argument("--me", required=True,
                    help="usuario(s) a buscar en las menciones, separados por comas")
    ap.add_argument("--accounts", required=True,
                    help="cuentas a revisar, separadas por comas (puede incluir la tuya)")
    ap.add_argument("--browser", default="brave")
    ap.add_argument("--out", default="burner_highlights.json")
    ap.add_argument("--wait", type=float, default=4.0)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Falta playwright:\n"
            "    pip3 install --user playwright\n"
            "    python3 -m playwright install chromium")

    terms = [t.strip().lstrip("@").lower() for t in args.me.split(",") if t.strip()]
    accounts = [a.strip().lstrip("@") for a in args.accounts.split(",") if a.strip()]
    cookies = load_cookies(args.browser)
    pw_cookies = [{"name": k, "value": v, "domain": ".instagram.com", "path": "/"}
                  for k, v in cookies.items()]

    print("=" * 62)
    print("  Escáner de DESTACADAS · ⚠️  ToS + riesgo para la burner")
    print("=" * 62)

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(locale="es-ES", viewport={"width": 1280, "height": 900})
        ctx.add_cookies(pw_cookies)
        page = ctx.new_page()
        for account in accounts:
            results.extend(scan_account(page, account, terms, args.wait, args.debug))
        browser.close()

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)

    print(f"\n→ Guardado {args.out}: {len(results)} destacadas con mención")
    if results:
        print("  Súbelo en el panel → ⭐ Cuentas destacadas → 📥 Importar menciones de historias")
    else:
        print("  No se encontró ninguna mención tuya en destacadas.")
        print("  (Es el resultado esperado si nunca se guardaron en destacadas.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

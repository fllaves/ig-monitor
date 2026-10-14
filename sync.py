"""Sincronización: descarga datos de Instagram vía Apify y los guarda en local.

Uso:
    python sync.py              # sincroniza con Apify (requiere APIFY_TOKEN)
    python sync.py --demo       # genera datos de demostración
    python sync.py --limit 200  # limita el número de publicaciones
"""
import argparse
import sys
from typing import Dict, List

import analytics
import config
import notify
import storage
from apify import InstagramSource


def _clear_demo_if_present() -> None:
    """Limpia la base si solo contiene datos de demostración."""
    if not storage.has_data():
        return
    runs = storage.get_runs()
    if runs and not any(r.get("source") == "apify" for r in runs):
        storage.reset_db()


def do_sync(token: str = "", limit: int = None, followers_limit: int = None,
            following_limit: int = None, demo: bool = False,
            with_comments: bool = True, with_mentions: bool = True,
            with_lists: bool = True, alert: bool = True) -> dict:
    """Ejecuta una sincronización completa y devuelve un resumen."""
    if demo:
        import demo as demo_mod
        demo_mod.seed_demo(clear=False)
        return {"source": "demo", "posts": 0, "followers": 0, "following": 0,
                "events": 0, "comments": 0, "mentions": 0,
                "message": "Datos de demostración añadidos.", "errors": []}

    _clear_demo_if_present()
    storage.init_db()
    source = InstagramSource(token or config.APIFY_TOKEN)
    captured_at = storage.utcnow()

    summary = {"source": "apify", "posts": 0, "followers": 0, "following": 0,
               "events": 0, "comments": 0, "mentions": 0, "errors": []}

    # 1) Perfil
    try:
        profile_items = source.fetch_profile()
        if profile_items:
            storage.save_profile_snapshot(profile_items[0], captured_at)
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"perfil: {exc}")

    # 2) Publicaciones
    try:
        posts = source.fetch_posts(limit=limit or config.RESULTS_LIMIT)
        summary["posts"] = storage.upsert_posts(posts, captured_at)
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"publicaciones: {exc}")

    # 3) Seguidores (lo MÁS caro del plan: omitido en modo económico)
    if with_lists:
        try:
            followers = source.fetch_followers(
                limit=followers_limit or config.FOLLOWERS_LIMIT)
            summary["followers"] = storage.save_relations(
                followers, "follower", captured_at)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"seguidores: {exc}")

    if with_lists:
        # 4) Seguidos
        try:
            following = source.fetch_following(limit=following_limit or config.FOLLOWING_LIMIT)
            summary["following"] = storage.save_relations(following, "following", captured_at)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"seguidos: {exc}")

    # 5) Registrar eventos de cambio (historial persistente)
    try:
        events = analytics.build_relation_events(storage.get_relation_history())
        summary["events"] = storage.save_relation_events(events)
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"eventos: {exc}")

    # 6) Comentarios de los posts con más engagement
    if with_comments:
        try:
            top = analytics.top_posts(storage.get_posts(),
                                      n=config.COMMENTS_TOP_POSTS, metric="likes")
            urls = [p.get("url") for p in top if p.get("url")]
            if urls:
                comments = source.fetch_comments(urls)
                summary["comments"] = storage.save_comments(comments, captured_at)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"comentarios: {exc}")

    # 7) Menciones (posts donde te etiquetan)
    if with_mentions:
        try:
            mentions = source.fetch_mentions()
            summary["mentions"] = storage.save_mentions(mentions, captured_at)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"menciones: {exc}")

    storage.save_run(captured_at, "sync", "", summary["posts"], source="apify",
                     followers_count=summary["followers"],
                     following_count=summary["following"])

    # 8) Alertas (Telegram)
    if alert:
        try:
            summary["alert"] = notify.check_and_alert(
                storage.get_relation_history(), storage.get_posts()
            )
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"alertas: {exc}")

    summary["message"] = "Sincronización completada."
    storage.log_ingest(
        "apify",
        "perfil+posts+seguidores+seguidos+comentarios+menciones",
        sum(summary.get(k, 0) for k in ("posts", "followers", "following", "comments", "mentions")),
        status="error" if summary["errors"] else "ok",
        message="; ".join(summary["errors"])[:300],
    )
    return summary


def do_watch_sync(token: str = "", accounts: list = None,
                  posts_per_account: int = 20, comments_per_post: int = 20,
                  max_post_urls: int = 60) -> dict:
    """Descarga posts + comentarios de las cuentas destacadas (Fase 1).

    Con eso se reconstruye la interacción pública: comentarios que TÚ dejas en
    sus posts, comentarios que ellos dejan, y qué publican.
    """
    storage.init_db()
    accounts = accounts or [w["username"] for w in storage.get_watchlist()]
    summary = {"accounts": len(accounts), "posts": 0, "comments": 0, "errors": []}
    if not accounts:
        summary["errors"].append("Sin cuentas destacadas.")
        return summary

    # El panel y la BD usan códigos: se traducen a usuario real solo para la API
    real_accounts = [config.real_username(a) for a in accounts]
    src = InstagramSource(token or config.APIFY_TOKEN)
    captured_at = storage.utcnow()

    posts = []
    try:
        posts = src.fetch_profiles_posts(real_accounts, limit=posts_per_account)
        summary["posts"] = storage.save_external_posts(posts, captured_at)
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"posts: {exc}")

    source_by_post = {}
    for p in posts:
        owner = config.to_code((p.get("ownerUsername") or "").lower())
        if p.get("url"):
            source_by_post[p["url"]] = owner
        if p.get("shortCode"):
            source_by_post[p["shortCode"]] = owner

    urls = [p.get("url") for p in posts if p.get("url")][:max_post_urls]
    if urls:
        try:
            comments = src.fetch_comments(urls, limit=comments_per_post)
            summary["comments"] = storage.save_external_comments(
                comments, source_by_post, captured_at)
        except Exception as exc:  # noqa: BLE001
            summary["errors"].append(f"comentarios: {exc}")

    summary["message"] = "Interacciones de destacadas actualizadas."
    storage.log_ingest(
        "apify-watch", "posts+comentarios de destacadas",
        summary["posts"] + summary["comments"],
        status="error" if summary["errors"] else "ok",
        message="; ".join(summary["errors"])[:300],
    )
    return summary


def do_threads_sync(token: str = None, accounts: List[str] = None) -> Dict:
    """Perfiles y publicaciones públicas de Threads de las cuentas destacadas.

    Threads es la única red (además de Instagram) que el proyecto puede leer sin
    tocar la cuenta propia: los perfiles públicos se consultan vía Apify.
    """
    from apify import ThreadsSource

    storage.init_db()  # asegura que exista la tabla threads_posts
    token = token or config.APIFY_TOKEN
    summary = {"accounts": 0, "posts": 0, "found": 0, "errors": [], "message": ""}
    if not token:
        summary["errors"].append("threads: falta APIFY_TOKEN")
        summary["message"] = "Sin token no se puede consultar Threads."
        return summary

    names = accounts or [w.get("username") for w in storage.get_watchlist()]
    names = [n for n in names if n]
    summary["accounts"] = len(names)
    if not names:
        summary["message"] = "No hay cuentas destacadas que consultar en Threads."
        return summary

    try:
        # El panel y la BD usan códigos: se traducen a usuario real solo para la API
        posts = ThreadsSource(token).fetch_posts(
            [config.real_username(n) for n in names])
        summary["posts"] = storage.save_threads_posts(posts)
        summary["found"] = len({p.get("username") for p in posts})
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"threads: {exc}")

    summary["message"] = (
        f"Threads: {summary['found']}/{summary['accounts']} cuentas encontradas, "
        f"{summary['posts']} publicaciones.")
    return summary


def do_linkedin_sync(token: str = None, profiles: List = None) -> Dict:
    """Actividad pública de LinkedIn (posts **y reposts**) de los perfiles añadidos.

    Funciona **sin cookies**: no hay sesión que comprometer, así que el riesgo no
    recae sobre la cuenta propia. El valor está en `repostedBy`/`repostedAt`: si
    alguien comparte tu contenido, queda registrado con fecha.
    """
    from apify import LinkedInSource

    storage.init_db()
    token = token or config.APIFY_TOKEN
    summary = {"profiles": 0, "items": 0, "shared_mine": 0, "errors": [], "message": ""}
    if not token:
        summary["errors"].append("linkedin: falta APIFY_TOKEN")
        summary["message"] = "Sin token no se puede consultar LinkedIn."
        return summary

    rows = profiles if profiles is not None else storage.get_linkedin_profiles()
    rows = [r for r in (rows or []) if (r or {}).get("url")]
    if not rows:
        summary["message"] = "No hay perfiles de LinkedIn añadidos todavía."
        return summary

    try:
        items = LinkedInSource(token).fetch_activity([r["url"] for r in rows])
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"linkedin: {exc}")
        summary["message"] = f"Error consultando LinkedIn: {exc}"
        return summary

    grupos: Dict[str, List] = {}
    for it in items:
        grupos.setdefault(it.get("profile") or "", []).append(it)
    for ident, grupo in grupos.items():
        if ident:
            summary["items"] += storage.save_linkedin_activity(ident, grupo)
            if any((g.get("reposted_by") or "") == ident for g in grupo):
                summary["shared_mine"] += sum(
                    1 for g in grupo if (g.get("reposted_by") or "") == ident)
    summary["profiles"] = len([k for k in grupos if k])
    summary["message"] = (
        f"LinkedIn: {summary['profiles']}/{len(rows)} perfiles, "
        f"{summary['items']} elementos.")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Sincroniza el monitoreo de Instagram")
    parser.add_argument("--demo", action="store_true", help="usa datos de demostración")
    parser.add_argument("--limit", type=int, default=None, help="límite de publicaciones")
    parser.add_argument("--followers-limit", type=int, default=None, help="límite de seguidores")
    parser.add_argument("--following-limit", type=int, default=None, help="límite de seguidos")
    parser.add_argument("--no-comments", action="store_true", help="no descargar comentarios")
    parser.add_argument("--no-mentions", action="store_true", help="no descargar menciones")
    parser.add_argument("--token", default="", help="token de Apify (o usa APIFY_TOKEN)")
    args = parser.parse_args()

    try:
        result = do_sync(
            token=args.token, limit=args.limit,
            followers_limit=args.followers_limit,
            following_limit=args.following_limit, demo=args.demo,
            with_comments=not args.no_comments,
            with_mentions=not args.no_mentions,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(result["message"])
    print(f"  posts: {result['posts']} | seguidores: {result['followers']} | "
          f"seguidos: {result['following']} | eventos: {result.get('events', 0)} | "
          f"comentarios: {result.get('comments', 0)} | menciones: {result.get('mentions', 0)}")
    if result.get("alert"):
        a = result["alert"]
        print(f"  alerta: {'enviada' if a.get('sent') else ('dry-run: ' + (a.get('message') or '') if a.get('dry_run') else a.get('reason') or a.get('info') or 'sin cambios')}")
    for err in result["errors"]:
        print(f"  ⚠ {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

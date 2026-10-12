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
            alert: bool = True) -> dict:
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

    # 3) Seguidores
    try:
        followers = source.fetch_followers(limit=followers_limit or config.FOLLOWERS_LIMIT)
        summary["followers"] = storage.save_relations(followers, "follower", captured_at)
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"seguidores: {exc}")

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

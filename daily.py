"""Rutina diaria del centro de monitoreo.

Hace, en orden:
  1) Sincroniza con Apify (perfil, posts, seguidores, seguidos, comentarios, menciones).
  2) Registra de qué fuentes se consumieron datos (ingest log).
  3) Construye el resumen de actividad del día.
  4) Lo envía por Telegram (si está configurado).

Pensado para ejecutarse UNA VEZ AL DÍA de forma automática:
  · GitHub Actions  → ver `.github/workflows/daily.yml`
  · cron local      → 0 8 * * * cd /ruta/ig-monitor && .venv/bin/python daily.py

Uso manual:
    python daily.py                # sync + resumen
    python daily.py --no-sync      # solo el resumen del día
    python daily.py --dry-run      # muestra el mensaje sin enviarlo
"""
import argparse
import sys

import analytics
import config
import notify
import storage
import sync


def main() -> int:
    ap = argparse.ArgumentParser(description="Rutina diaria del centro de monitoreo")
    ap.add_argument("--no-sync", action="store_true", help="no sincronizar, solo resumen")
    ap.add_argument("--dry-run", action="store_true", help="no enviar por Telegram")
    ap.add_argument("--limit", type=int, default=None, help="límite de publicaciones")
    ap.add_argument("--watch", action="store_true", help="sincronizar también las cuentas destacadas")
    ap.add_argument("--full", action="store_true",
                    help="sincronización COMPLETA (comentarios, listas de seguidores y LinkedIn). "
                         "Caro: ~$0.40 por corrida")
    ap.add_argument("--lean", action="store_true",
                    help="modo económico explícito (es el comportamiento por defecto)")
    args = ap.parse_args()

    # Modo económico por defecto: el plan gratuito da $5 al mes y las listas de
    # seguidores + los comentarios son lo que más gasta. Lo caro va en --full.
    lean = not args.full
    storage.init_db()
    print(f"=== Rutina diaria · {config.DISPLAY_NAME} ===")
    print(f"    modo: {'ECONÓMICO (~$0.02)' if lean else 'COMPLETO (~$0.40)'}"
          + ("" if lean else "  ← solo de vez en cuando"))

    result = None
    if not args.no_sync:
        if not config.APIFY_TOKEN:
            print("⚠ Sin APIFY_TOKEN: me salto la sincronización.", file=sys.stderr)
            storage.log_ingest("apify", "rutina diaria", 0, status="error",
                               message="Falta APIFY_TOKEN")
        else:
            print("→ Sincronizando con Apify…")
            try:
                result = sync.do_sync(
                    token=config.APIFY_TOKEN,
                    limit=args.limit or (25 if lean else None),
                    with_lists=not lean,
                    with_comments=not lean,
                    with_mentions=not lean,
                    alert=False)
                print(f"  {result.get('message', '')}")
                for err in result.get("errors", []):
                    print(f"  ⚠ {err}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print(f"  ✖ Error: {exc}", file=sys.stderr)
                storage.log_ingest("apify", "rutina diaria", 0, status="error",
                                   message=str(exc)[:300])
            # Threads es BARATO (~$0.02): se consulta siempre.
            try:
                print("→ Consultando Threads…")
                tres = sync.do_threads_sync(token=config.APIFY_TOKEN)
                print(f"  {tres.get('message', '')}")
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠ threads: {exc}", file=sys.stderr)

            # LinkedIn y las interacciones de destacadas son CAROS (~$0.30):
            # solo en modo completo (--full) o si se pide --watch explícito.
            if args.watch and not lean:
                try:
                    print("→ Sincronizando interacciones de destacadas…")
                    wres = sync.do_watch_sync(token=config.APIFY_TOKEN)
                    print(f"  {wres.get('posts', 0)} posts / {wres.get('comments', 0)} comentarios")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ⚠ destacadas: {exc}", file=sys.stderr)
                try:
                    print("→ Consultando LinkedIn…")
                    lres = sync.do_linkedin_sync(token=config.APIFY_TOKEN)
                    print(f"  {lres.get('message', '')}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ⚠ linkedin: {exc}", file=sys.stderr)

    digest = analytics.daily_digest(
        storage.get_relation_events(),
        storage.get_posts(),
        storage.get_comments(),
        storage.get_mentions(),
        storage.get_ingest_log(300),
    )

    message = notify.build_daily_message(digest, result)
    print("\n" + message + "\n")

    res = notify.send_daily_digest(digest, result, dry_run=args.dry_run)
    if res.get("dry_run"):
        print("(dry-run: mensaje no enviado)")
    elif res.get("sent"):
        print("✔ Resumen enviado por Telegram")
    else:
        print(f"⚠ No se envió por Telegram: {res.get('info')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Sube los datos de la base LOCAL a una base remota (Turso).

Sirve como plan B: si pierdes la conexión con tu base en la nube, tus datos
locales se pueden volver a subir sin perder nada.

Uso:
    1) Pon las credenciales del destino en `.env`:
           DATABASE_URL=libsql://tu-base.turso.io
           DATABASE_AUTH_TOKEN=eyJ...
    2) python3 cloud_push.py --dry-run     # ver qué se subiría
       python3 cloud_push.py               # subir de verdad

⚠️ Hace INSERT OR REPLACE: no borra lo que ya esté en el destino, pero sí
   sobrescribe las filas con la misma clave.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import config
import storage

TABLAS = [
    "runs", "profile_history", "posts", "post_history", "relation_history",
    "relation_events", "comments", "mentions", "account_profiles", "watchlist",
    "external_posts", "external_comments", "story_mentions", "ingest_log",
    "threads_posts", "linkedin_profiles", "linkedin_activity", "story_archive",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Sube la base local a Turso")
    ap.add_argument("--dry-run", action="store_true", help="solo contar, no escribir")
    args = ap.parse_args()

    if not config.DATABASE_URL:
        print("❌ Falta DATABASE_URL en `.env` (el destino).\n"
              "   Añade la URL y el DATABASE_AUTH_TOKEN de tu base de Turso.")
        return 1

    origen = Path(config.DB_PATH)
    if not origen.exists():
        print(f"❌ No encuentro la base local: {origen}")
        return 1

    print(f"→ Origen : {origen}")
    print(f"→ Destino: {config.DATABASE_URL}")
    print(f"→ Modo   : {'SIMULACIÓN (no escribe)' if args.dry_run else 'ESCRITURA REAL'}\n")

    src = sqlite3.connect(str(origen))
    src.row_factory = sqlite3.Row

    if args.dry_run:
        total = 0
        for t in TABLAS:
            try:
                n = src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                continue
            total += n
            print(f"  {t:<20} {n:>6} filas")
        print(f"\n  TOTAL: {total} filas se subirían.")
        src.close()
        return 0

    # Crea el esquema en el destino y sube todo
    storage.init_db()
    destino = storage._connect()
    subidas = 0
    for t in TABLAS:
        try:
            cols = [r[1] for r in src.execute(f"PRAGMA table_info({t})").fetchall()]
            if not cols:
                continue
            filas = src.execute(f"SELECT * FROM {t}").fetchall()
        except sqlite3.Error:
            continue
        if not filas:
            continue
        marcadores = ", ".join("?" * len(cols))
        sql = (f"INSERT OR REPLACE INTO {t}({', '.join(cols)}) VALUES ({marcadores})")
        for fila in filas:
            try:
                destino.execute(sql, tuple(fila))
                subidas += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠️  {t}: {exc}", file=sys.stderr)
        print(f"  ✅ {t:<20} {len(filas):>6} filas")

    storage._close(destino)   # commit + sync al remoto
    src.close()
    print(f"\n✔ Subidas {subidas} filas a {config.DATABASE_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

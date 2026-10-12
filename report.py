"""Genera un informe semanal en Excel (.xlsx) con toda la actividad.

Uso:
    python report.py                # escribe data/informe_YYYYMMDD.xlsx
    python report.py --out ruta.xlsx
"""
import argparse
import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import analytics
import config
import storage

HEADER_FILL = PatternFill("solid", fgColor="6366F1")
HEADER_FONT = Font(color="FFFFFF", bold=True)
TITLE_FONT = Font(bold=True, size=14)


def _write_sheet(ws, headers, rows):
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="left")
    for row in rows:
        ws.append(row)
    # ancho de columnas
    for i, h in enumerate(headers, start=1):
        col = get_column_letter(i)
        max_len = max([len(str(h))] + [len(str(r[i - 1])) if i - 1 < len(r) else 0 for r in rows] or [len(str(h))])
        ws.column_dimensions[col].width = min(max(max_len + 2, 10), 60)


def build_report_bytes() -> bytes:
    storage.init_db()

    history = storage.get_profile_history()
    latest = history[-1] if history else None
    prev = history[-2] if len(history) >= 2 else None
    followers = (latest or {}).get("followers_count") or 0
    posts = analytics.enrich_posts(storage.get_posts(), followers)
    kpis = analytics.compute_kpis(posts, latest, prev)

    rel = storage.get_relation_history()
    f_members = analytics.relation_members(rel, "follower")
    g_members = analytics.relation_members(rel, "following")
    mutuals = analytics.compute_mutuals(rel)
    quality = analytics.audience_quality(f_members)
    comments = storage.get_comments()
    cstats = analytics.comment_stats(comments)
    mentions = storage.get_mentions()
    events = storage.get_relation_events()

    wb = Workbook()

    # --- Resumen ---
    ws = wb.active
    ws.title = "Resumen"
    ws["A1"] = f"Informe de {config.DISPLAY_NAME}"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')} (UTC)"
    summary_rows = [
        ("Seguidores", kpis["followers"]),
        ("Siguiendo", kpis["following"]),
        ("Publicaciones", kpis["posts"]),
        ("Likes promedio", kpis["avg_likes"]),
        ("Comentarios promedio", kpis["avg_comments"]),
        ("Engagement rate (%)", kpis["avg_engagement_rate"]),
        ("Seguidores (lista)", len(f_members)),
        ("Seguidos (lista)", len(g_members)),
        ("Mutuales", len(mutuals["mutuals"])),
        ("Comentarios capturados", cstats["total"]),
        ("Comentarios positivos", cstats["positive"]),
        ("Comentarios neutrales", cstats["neutral"]),
        ("Comentarios negativos", cstats["negative"]),
        ("Audiencia verificada", quality["verified"]),
        ("Audiencia privada", quality["private"]),
        ("Cuentas sospechosas", quality["suspicious"]),
    ]
    r = 4
    for label, value in summary_rows:
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        ws.cell(row=r, column=2, value=value)
        r += 1
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 20

    # --- Publicaciones ---
    ws = wb.create_sheet("Publicaciones")
    _write_sheet(ws, ["Fecha", "Tipo", "Caption", "Likes", "Comentarios", "Vistas", "ER %", "URL"],
                 [[(p.get("dt").strftime("%Y-%m-%d %H:%M") if p.get("dt") else ""),
                   p.get("content_type"),
                   (p.get("caption") or "")[:120],
                   p.get("likesCount"),
                   p.get("commentsCount"),
                   p.get("videoPlayCount") or p.get("videoViewCount") or 0,
                   p.get("engagement_rate"),
                   p.get("url") or ""] for p in posts])

    # --- Seguidores ---
    ws = wb.create_sheet("Seguidores")
    _write_sheet(ws, ["Usuario", "Nombre", "Verificado", "Privado", "Visto desde", "Visto hasta"],
                 [[m.get("username"), m.get("full_name"), m.get("is_verified"),
                   m.get("is_private"), (m.get("first_seen") or "")[:10],
                   (m.get("last_seen") or "")[:10]] for m in f_members])

    # --- Seguidos ---
    ws = wb.create_sheet("Seguidos")
    _write_sheet(ws, ["Usuario", "Nombre", "Verificado", "Privado", "Visto desde", "Visto hasta"],
                 [[m.get("username"), m.get("full_name"), m.get("is_verified"),
                   m.get("is_private"), (m.get("first_seen") or "")[:10],
                   (m.get("last_seen") or "")[:10]] for m in g_members])

    # --- Cambios ---
    ws = wb.create_sheet("Cambios")
    _write_sheet(ws, ["Fecha", "Evento", "Usuario", "Nombre"],
                 [[(e.get("detected_at") or "")[:19], e.get("event_type"),
                   e.get("username"), e.get("full_name")] for e in events])

    # --- Comentarios ---
    ws = wb.create_sheet("Comentarios")
    _write_sheet(ws, ["Fecha", "Post", "Usuario", "Texto", "Sentimiento", "Likes"],
                 [[(c.get("timestamp") or "")[:19], c.get("post_id"),
                   c.get("owner_username"), (c.get("text") or "")[:150],
                   analytics.sentiment(c.get("text")), c.get("likes_count")]
                  for c in comments])

    # --- Menciones ---
    ws = wb.create_sheet("Menciones")
    _write_sheet(ws, ["Fecha", "Quién", "Caption", "Likes", "URL"],
                 [[(m.get("timestamp") or "")[:19], m.get("owner_username"),
                   (m.get("caption") or "")[:120], m.get("likes_count"),
                   m.get("url") or ""] for m in mentions])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_report(path: str) -> str:
    data = build_report_bytes()
    with open(path, "wb") as f:
        f.write(data)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera el informe Excel")
    parser.add_argument("--out", default=None, help="ruta de salida del .xlsx")
    args = parser.parse_args()

    out = args.out or str(config.BASE_DIR / "data" /
                          f"informe_{datetime.now().strftime('%Y%m%d')}.xlsx")
    generate_report(out)
    print(f"Informe generado: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

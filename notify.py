"""Alertas automáticas vía Telegram (opcional).

Cuando se produce una sincronización, `check_and_alert` compara las listas de
seguidores/seguidos con la sincronización anterior y, si hay cambios o un reel
supera el umbral de reproducciones, envía un mensaje por Telegram.

Para activarlo, añade en `.env`:
    TELEGRAM_BOT_TOKEN=123456:ABC-...
    TELEGRAM_CHAT_ID=123456789
El bot se crea hablando con @BotFather en Telegram.
"""
import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import analytics
import config


def send_telegram(message: str) -> Tuple[bool, str]:
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return False, "Telegram no configurado (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            ok = bool(body.get("ok"))
            return ok, ("enviado" if ok else body.get("description", "error"))
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def build_alert_message(deltas: List[Dict], posts: Optional[List[Dict]] = None,
                        views_threshold: int = 0) -> Optional[str]:
    lines: List[str] = []

    for d in deltas:
        rtype = d["relation_type"]
        if rtype == "follower":
            lost_verb = "te dejaron de seguir"
            new_label = "Nuevos seguidores"
        else:
            lost_verb = "dejaste de seguir"
            new_label = "Nuevos seguidos"

        if d["lost"]:
            names = ", ".join(f"@{a['username']}" for a in d["lost"][:15])
            extra = f" (+{len(d['lost']) - 15} más)" if len(d['lost']) > 15 else ""
            lines.append(f"🔻 {len(d['lost'])} {lost_verb}: {names}{extra}")
        if d["new"]:
            names = ", ".join(f"@{a['username']}" for a in d["new"][:15])
            extra = f" (+{len(d['new']) - 15} más)" if len(d['new']) > 15 else ""
            lines.append(f"🟢 {new_label} ({len(d['new'])}): {names}{extra}")

    if posts and views_threshold and views_threshold > 0:
        hot = [p for p in posts if (p.get("videoPlayCount") or 0) > views_threshold]
        if hot:
            top = max(hot, key=lambda p: p.get("videoPlayCount") or 0)
            lines.append(
                f"🚀 Reel con {top.get('videoPlayCount'):,} reproducciones: "
                f"{top.get('url') or top.get('shortCode')}"
            )

    return "\n".join(lines) if lines else None


def check_and_alert(relation_history: List[Dict], posts: Optional[List[Dict]] = None,
                    dry_run: bool = False) -> Dict[str, Any]:
    deltas = [
        d for d in (
            analytics.relation_delta(relation_history, "follower"),
            analytics.relation_delta(relation_history, "following"),
        ) if d
    ]
    message = build_alert_message(deltas, posts, config.ALERT_VIEWS_THRESHOLD)

    if not message:
        return {"sent": False, "reason": "nada que alertar", "message": None}

    if dry_run:
        return {"sent": False, "dry_run": True, "message": message}

    ok, info = send_telegram(message)
    return {"sent": ok, "info": info, "message": message}


def build_daily_message(digest: Dict[str, Any], sync_result: Dict = None) -> str:
    """Construye el resumen diario de actividad para Telegram."""
    d = digest
    lines = [f"📊 Actividad de {config.DISPLAY_NAME} · {d['day']}", ""]
    lines.append(f"📝 Posts publicados: {d['posts']}")
    if d["posts"]:
        lines.append(f"❤️ Likes en esos posts: {d['likes']:,}")
    lines.append(f"💬 Comentarios recibidos: {d['comments_received']}")
    lines.append(f"🏷️ Menciones recibidas: {d['mentions_received']}")
    lines.append(f"👥 Seguidores: +{d['new_followers']} / −{d['lost_followers']} "
                 f"(neto {d['net_followers']:+d})")
    lines.append(f"🔁 Seguidos: +{d['new_following']} / −{d['lost_following']}")

    if d.get("new_follower_names"):
        lines.append("")
        lines.append("🟢 Nuevos seguidores: "
                     + ", ".join(f"@{u}" for u in d["new_follower_names"][:10]))
    if d.get("lost_follower_names"):
        lines.append("🔻 Te dejaron de seguir: "
                     + ", ".join(f"@{u}" for u in d["lost_follower_names"][:10]))
    if d.get("commenters"):
        lines.append("💬 Comentaron: "
                     + ", ".join(f"@{u}" for u in d["commenters"][:10]))

    if d.get("sources"):
        fuentes = sorted({(s.get("source") or "?") for s in d["sources"]})
        lines.append("")
        lines.append("🗂️ Fuentes de datos hoy: " + ", ".join(fuentes))

    if sync_result:
        lines.append("")
        lines.append(f"🔄 Sincronización: {sync_result.get('posts', 0)} posts · "
                     f"{sync_result.get('followers', 0)} seguidores · "
                     f"{sync_result.get('following', 0)} seguidos")
        for err in (sync_result.get("errors") or [])[:3]:
            lines.append(f"⚠ {err}")

    return "\n".join(lines)


def send_daily_digest(digest: Dict[str, Any], sync_result: Dict = None,
                      dry_run: bool = False) -> Dict[str, Any]:
    """Envía (o simula) el resumen diario por Telegram."""
    message = build_daily_message(digest, sync_result)
    if dry_run:
        return {"sent": False, "dry_run": True, "message": message}
    ok, info = send_telegram(message)
    return {"sent": ok, "info": info, "message": message}

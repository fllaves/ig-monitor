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
import time
import urllib.parse
import urllib.request
from pathlib import Path
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


def send_telegram_photo(photo_path: str, caption: str = "") -> Tuple[bool, str]:
    """Envía una imagen por Telegram (multipart/form-data, sin dependencias)."""
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return False, "Telegram no configurado"
    try:
        datos = Path(photo_path).read_bytes()
    except OSError as exc:
        return False, f"no pude leer {photo_path}: {exc}"

    boundary = f"----IGFV{int(time.time() * 1000)}"
    partes: List[bytes] = []
    for nombre, valor in (("chat_id", str(chat_id)), ("caption", (caption or "")[:1000])):
        partes.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{nombre}"'
            f"\r\n\r\n{valor}\r\n".encode("utf-8"))
    partes.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
        f'filename="{Path(photo_path).name}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode("utf-8")
        + datos + b"\r\n")
    partes.append(f"--{boundary}--\r\n".encode("utf-8"))

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=b"".join(partes),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            ok = bool(body.get("ok"))
            return ok, ("enviado" if ok else body.get("description", "error"))
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def build_stories_report(stories: List[Dict], day: str = "") -> str:
    """Informe diario de historias: cuántas, de quién y a quién etiqueta cada una.

    Las etiquetas se muestran **por cuenta** (no por historia) porque Instagram
    precarga los datos de todas las historias en cada página: si no, la misma
    mención aparecería repetida en cada historia.
    """
    if not stories:
        return f"📸 Historias · {day}\n\nNo se capturó ninguna."

    import config as _cfg
    mia = {(_cfg.DISPLAY_NAME or "").upper(), _cfg.to_code(_cfg.USERNAME).upper()}

    def _url(u: str) -> str:
        """URL completa del perfil (el mensaje pedía el enlace, no solo @user)."""
        return f"https://instagram.com/{u}"

    por_cuenta: Dict[str, List[Dict]] = {}
    for s in stories:
        por_cuenta.setdefault(s.get("username") or "?", []).append(s)

    lineas = [f"📸 Historias capturadas · {day}", ""]

    # 🚨 Lo primero: quién te etiquetó a TI
    mencionan = [s for s in stories if s.get("mentions_me")]
    if mencionan:
        lineas.append("🚨 **¡TE ETIQUETARON EN UNA HISTORIA!**")
        for s in mencionan:
            tipo = "🎬 video" if s.get("kind") == "video" else "🖼️ foto"
            hora = str(s.get("taken_at") or "")[:16]
            lineas.append(f"  · **{s.get('username')}** — {tipo} · {hora}")
            if s.get("media_path"):
                lineas.append(f"    (guardada en {s['media_path']})")
        lineas.append("")
    etiquetados: Dict[str, Dict[str, int]] = {}
    total_mentions = 0

    for cuenta in sorted(por_cuenta):
        grupo = por_cuenta[cuenta]
        es_mia = cuenta.upper() in mia
        etiquetas_cuenta: List[str] = []
        for s in grupo:
            for m in (s.get("mentions") or []):
                if m not in etiquetas_cuenta:
                    etiquetas_cuenta.append(m)
                    etiquetados.setdefault(m, {})
                    etiquetados[m][cuenta] = etiquetados[m].get(cuenta, 0) + 1
                    total_mentions += 1

        lineas.append(f"**{cuenta}**{' (tú)' if es_mia else ''} — "
                      f"{len(grupo)} historia(s)")
        if etiquetas_cuenta:
            lineas.append("  🏷️ Etiqueta a:")
            for m in etiquetas_cuenta:
                lineas.append(f"    · @{m}")
                lineas.append(f"      {_url(m)}")
        for s in grupo:
            tipo = "🎬" if s.get("kind") == "video" else "🖼️"
            hora = str(s.get("taken_at") or "")[11:16]
            extra = []
            if s.get("mentions_me"):
                extra.append("⬅️ TE MENCIONA")
            if s.get("links"):
                extra.append("🔗 enlace")
            lineas.append(f"  {tipo} {hora}" + (" · " + " · ".join(extra) if extra else ""))
        lineas.append("")

    if etiquetados:
        lineas.append("👥 **Personas etiquetadas hoy:**")
        for usuario, quien in sorted(etiquetados.items()):
            detalle = ", ".join(sorted(quien))
            lineas.append(f"  · @{usuario}  (por {detalle})")
            lineas.append(f"    {_url(usuario)}")
        lineas.append("")

    lineas.append(f"Total: {len(stories)} historias · {total_mentions} etiqueta(s)")
    if not etiquetados:
        lineas.append("(Sin etiquetas detectadas)")
    return "\n".join(lineas).strip()


def send_daily_digest(digest: Dict[str, Any], sync_result: Dict = None,
                      dry_run: bool = False) -> Dict[str, Any]:
    """Envía (o simula) el resumen diario por Telegram."""
    message = build_daily_message(digest, sync_result)
    if dry_run:
        return {"sent": False, "dry_run": True, "message": message}
    ok, info = send_telegram(message)
    return {"sent": ok, "info": info, "message": message}

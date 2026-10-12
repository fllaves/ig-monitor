"""Configuración central del centro de monitoreo de Instagram.

Lee los valores en este orden de prioridad:
    1. Variables de entorno.
    2. Archivo `.env` (se carga si existe).
    3. Secretos de Streamlit Cloud (`st.secrets`, para el despliegue en la nube).

Sin dependencias externas obligatorias.
"""
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Carga pares KEY=VALUE de un archivo .env, sin pisar variables ya definidas."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _streamlit_secrets() -> dict:
    """Devuelve los secretos de Streamlit Cloud si están disponibles."""
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            return dict(st.secrets)
    except Exception:  # noqa: BLE001
        pass
    return {}


_load_dotenv(BASE_DIR / ".env")
_SECRETS = _streamlit_secrets()


def _get(key: str, default: str = "") -> str:
    if key in os.environ and os.environ[key] != "":
        return os.environ[key]
    val = _SECRETS.get(key)
    if val not in (None, ""):
        return str(val)
    return default


def _int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


# --- Cuenta objetivo ---------------------------------------------------------
# El username real NUNCA se escribe en el código: vive solo en `.env` (local) o
# en los secretos de Streamlit Cloud. Aquí solo hay un nombre visible neutro.
USERNAME = _get("IG_USERNAME", "").strip().lstrip("@")
DISPLAY_NAME = _get("DISPLAY_NAME", "IG FV").strip() or "IG FV"
PROFILE_URL = f"https://www.instagram.com/{USERNAME}/" if USERNAME else ""


def mask(text):
    """Oculta cualquier aparición del username real en textos mostrados."""
    if not text or not USERNAME:
        return text
    return re.sub(re.escape(USERNAME), DISPLAY_NAME, str(text), flags=re.IGNORECASE)

# --- Apify -------------------------------------------------------------------
APIFY_TOKEN = _get("APIFY_TOKEN", "").strip()

# Actor principal: perfil + publicaciones + comentarios + menciones
ACTOR_ID = _get("ACTOR_ID", "apify~instagram-scraper")
# Actor dedicado: listas de seguidores y seguidos
FOLLOWERS_ACTOR_ID = _get("FOLLOWERS_ACTOR_ID", "apify~instagram-followers-following-scraper")

RESULTS_LIMIT = _int("RESULTS_LIMIT", 100)
FOLLOWERS_LIMIT = _int("FOLLOWERS_LIMIT", 200)
FOLLOWING_LIMIT = _int("FOLLOWING_LIMIT", 200)

# Comentarios y menciones
COMMENTS_TOP_POSTS = _int("COMMENTS_TOP_POSTS", 10)
COMMENTS_PER_POST = _int("COMMENTS_PER_POST", 20)
MENTIONS_LIMIT = _int("MENTIONS_LIMIT", 20)

# --- Alertas (Telegram) ------------------------------------------------------
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID", "").strip()
ALERT_VIEWS_THRESHOLD = _int("ALERT_VIEWS_THRESHOLD", 0)

# --- Almacenamiento ----------------------------------------------------------
# Base local por defecto. Si defines DATABASE_URL (libsql://... de Turso),
# los datos se guardan en la nube (persistente en Streamlit Cloud).
DATABASE_URL = _get("DATABASE_URL", "").strip()
DATABASE_AUTH_TOKEN = _get("DATABASE_AUTH_TOKEN", "").strip()

DB_PATH = BASE_DIR / "data" / "instagram_monitor.db"

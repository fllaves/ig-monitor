"""Capa de persistencia: acumula el historial de monitoreo en SQLite local.

Cada sincronización guarda una "foto" del perfil, del estado de cada
publicación y de las listas de seguidores/seguidos. Como cada snapshot queda
fechado, se pueden reconstruir series temporales y detectar cambios
(quién te dejó de seguir, a quién dejaste de seguir, etc.).

Para no perder ningún dato, además de las columnas estructuradas se conserva
el JSON crudo (`raw_json`) de cada item tal como lo entrega Apify.
"""
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import config


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect():
    """Conexión a la base: local (sqlite3) o remota (libSQL/Turso)."""
    if config.DATABASE_URL:
        return _connect_remote()
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


_LAST_REMOTE_ERROR = None


def _sync(conn) -> None:
    """Sincroniza la réplica con la nube (solo libsql) y guarda el error."""
    global _LAST_REMOTE_ERROR
    sync_fn = getattr(conn, "sync", None)
    if sync_fn is None:
        return
    try:
        sync_fn()
        _LAST_REMOTE_ERROR = None
    except Exception as exc:  # noqa: BLE001
        _LAST_REMOTE_ERROR = str(exc)


def last_remote_error():
    return _LAST_REMOTE_ERROR


def _connect_remote():
    """Conexión a una base libSQL (Turso) usando una réplica local efímera."""
    try:
        import libsql
    except ImportError as exc:
        raise RuntimeError(
            "Falta la dependencia 'libsql'. Instálala con: pip install libsql"
        ) from exc
    # En la nube la carpeta puede no existir (data/ está en .gitignore)
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = libsql.connect(
        str(config.DB_PATH),
        sync_url=config.DATABASE_URL,
        auth_token=config.DATABASE_AUTH_TOKEN or None,
    )
    _sync(conn)  # trae el estado más reciente desde la nube
    return conn


def _close(conn) -> None:
    """Commit + sync (si es remoto) + cierre, registrando errores."""
    try:
        conn.commit()
    except Exception:  # noqa: BLE001
        pass
    _sync(conn)
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def diagnose() -> dict:
    """Prueba escritura + lectura contra la base activa (para depurar)."""
    result = {
        "backend": "libsql (Turso)" if config.DATABASE_URL else "sqlite local",
        "username_configurado": bool(config.USERNAME),
        "write_ok": False,
        "read_ok": False,
        "error": None,
    }
    try:
        init_db()
        marker = utcnow()
        conn = _connect()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _diag"
            " (id INTEGER PRIMARY KEY AUTOINCREMENT, marker TEXT)"
        )
        conn.execute("INSERT INTO _diag(marker) VALUES (?)", (marker,))
        _close(conn)
        rows = _rows("SELECT marker FROM _diag ORDER BY id DESC LIMIT 1")
        result["write_ok"] = True
        result["read_ok"] = bool(rows) and rows[0].get("marker") == marker
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    if not result["error"]:
        result["error"] = _LAST_REMOTE_ERROR
    return result



_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    run_id           TEXT,
    results_type     TEXT,
    items_count      INTEGER DEFAULT 0,
    followers_count  INTEGER DEFAULT 0,
    following_count  INTEGER DEFAULT 0,
    source           TEXT DEFAULT 'apify'
);

CREATE TABLE IF NOT EXISTS profile_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at       TEXT NOT NULL,
    username          TEXT,
    full_name         TEXT,
    biography         TEXT,
    followers_count   INTEGER,
    follows_count     INTEGER,
    posts_count       INTEGER,
    verified          INTEGER DEFAULT 0,
    is_business       INTEGER DEFAULT 0,
    business_category TEXT,
    profile_pic_url   TEXT,
    external_url      TEXT,
    raw_json          TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    post_id           TEXT PRIMARY KEY,
    short_code        TEXT,
    url               TEXT,
    caption           TEXT,
    type              TEXT,
    product_type      TEXT,
    likes_count       INTEGER,
    comments_count    INTEGER,
    video_view_count  INTEGER,
    video_play_count  INTEGER,
    published_at      TEXT,
    display_url       TEXT,
    is_pinned         INTEGER DEFAULT 0,
    hashtags          TEXT,
    mentions          TEXT,
    first_captured_at TEXT,
    last_captured_at  TEXT,
    raw_json          TEXT
);

CREATE TABLE IF NOT EXISTS post_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id        TEXT,
    captured_at    TEXT NOT NULL,
    likes_count    INTEGER,
    comments_count INTEGER,
    view_count     INTEGER
);

CREATE TABLE IF NOT EXISTS relation_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at     TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    relation_type   TEXT NOT NULL,
    username        TEXT,
    full_name       TEXT,
    profile_pic_url TEXT,
    is_verified     INTEGER DEFAULT 0,
    is_private      INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_post_history_post ON post_history(post_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_profile_history_captured ON profile_history(captured_at);
CREATE INDEX IF NOT EXISTS idx_relation_history_type ON relation_history(relation_type, captured_at);
CREATE INDEX IF NOT EXISTS idx_relation_history_user ON relation_history(user_id, relation_type, captured_at);

CREATE TABLE IF NOT EXISTS relation_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type      TEXT NOT NULL,
    relation_type   TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    username        TEXT,
    full_name       TEXT,
    profile_pic_url TEXT,
    detected_at     TEXT NOT NULL,
    UNIQUE(user_id, relation_type, event_type, detected_at)
);

CREATE TABLE IF NOT EXISTS comments (
    id             TEXT PRIMARY KEY,
    post_id        TEXT,
    post_url       TEXT,
    text           TEXT,
    owner_username TEXT,
    owner_id       TEXT,
    likes_count    INTEGER,
    timestamp      TEXT,
    captured_at    TEXT,
    raw_json       TEXT
);

CREATE TABLE IF NOT EXISTS mentions (
    id             TEXT PRIMARY KEY,
    short_code     TEXT,
    url            TEXT,
    caption        TEXT,
    owner_username TEXT,
    timestamp      TEXT,
    likes_count    INTEGER,
    captured_at    TEXT,
    raw_json       TEXT
);

CREATE INDEX IF NOT EXISTS idx_relation_events_detected ON relation_events(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_mentions_captured ON mentions(captured_at);
"""


def init_db() -> None:
    conn = _connect()
    conn.executescript(_SCHEMA)
    _close(conn)


def reset_db() -> None:
    """Borra todos los datos y deja el esquema vacío listo para usar."""
    conn = _connect()
    conn.executescript(
        "DROP TABLE IF EXISTS relation_events;"
        "DROP TABLE IF EXISTS mentions;"
        "DROP TABLE IF EXISTS comments;"
        "DROP TABLE IF EXISTS relation_history;"
        "DROP TABLE IF EXISTS post_history;"
        "DROP TABLE IF EXISTS posts;"
        "DROP TABLE IF EXISTS profile_history;"
        "DROP TABLE IF EXISTS runs;"
    )
    _close(conn)
    init_db()


# --- Escritura ---------------------------------------------------------------

def save_run(started_at: str, results_type: str, run_id: str,
             items_count: int, source: str = "apify",
             followers_count: int = 0, following_count: int = 0,
             finished_at: Optional[str] = None) -> int:
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO runs(started_at, finished_at, run_id, results_type, items_count,"
        " followers_count, following_count, source)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (started_at, finished_at or utcnow(), run_id, results_type, items_count,
         followers_count, following_count, source),
    )
    conn.commit()
    try:
        run_pk = cur.lastrowid
    except Exception:  # noqa: BLE001
        run_pk = None
    _close(conn)
    return run_pk


def save_profile_snapshot(profile: Dict[str, Any], captured_at: str) -> None:
    conn = _connect()
    conn.execute(
        """
        INSERT INTO profile_history(
            captured_at, username, full_name, biography,
            followers_count, follows_count, posts_count,
            verified, is_business, business_category,
            profile_pic_url, external_url, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            captured_at,
            profile.get("username"),
            profile.get("fullName"),
            profile.get("biography"),
            profile.get("followersCount"),
            profile.get("followsCount"),
            profile.get("postsCount"),
            1 if profile.get("verified") else 0,
            1 if profile.get("isBusinessAccount") else 0,
            profile.get("businessCategoryName"),
            profile.get("profilePicUrl"),
            profile.get("externalUrl"),
            json.dumps(profile, ensure_ascii=False),
        ),
    )
    _close(conn)


def upsert_posts(items: Iterable[Dict[str, Any]], captured_at: str) -> int:
    """Guarda/actualiza publicaciones y añade su métrica al historial."""
    conn = _connect()
    count = 0
    for item in items:
        post_id = str(item.get("id") or item.get("shortCode") or item.get("url") or "")
        if not post_id:
            continue
        hashtags = json.dumps(item.get("hashtags") or [], ensure_ascii=False)
        mentions = json.dumps(item.get("mentions") or [], ensure_ascii=False)
        raw = json.dumps(item, ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO posts(
                post_id, short_code, url, caption, type, product_type,
                likes_count, comments_count, video_view_count, video_play_count,
                published_at, display_url, is_pinned, hashtags, mentions,
                first_captured_at, last_captured_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
                url = excluded.url,
                caption = excluded.caption,
                type = excluded.type,
                product_type = excluded.product_type,
                likes_count = excluded.likes_count,
                comments_count = excluded.comments_count,
                video_view_count = excluded.video_view_count,
                video_play_count = excluded.video_play_count,
                published_at = excluded.published_at,
                display_url = excluded.display_url,
                is_pinned = excluded.is_pinned,
                hashtags = excluded.hashtags,
                mentions = excluded.mentions,
                last_captured_at = excluded.last_captured_at,
                raw_json = excluded.raw_json
            """,
            (
                post_id,
                item.get("shortCode"),
                item.get("url"),
                item.get("caption"),
                item.get("type"),
                item.get("productType"),
                item.get("likesCount"),
                item.get("commentsCount"),
                item.get("videoViewCount"),
                item.get("videoPlayCount"),
                item.get("timestamp"),
                item.get("displayUrl"),
                1 if item.get("isPinned") else 0,
                hashtags,
                mentions,
                captured_at,
                captured_at,
                raw,
            ),
        )
        conn.execute(
            """
            INSERT INTO post_history(post_id, captured_at, likes_count, comments_count, view_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                post_id,
                captured_at,
                item.get("likesCount"),
                item.get("commentsCount"),
                item.get("videoPlayCount") or item.get("videoViewCount"),
            ),
        )
        count += 1
    _close(conn)
    return count


def save_relations(items: Iterable[Dict[str, Any]], relation_type: str,
                   captured_at: str) -> int:
    """Guarda una lista de seguidores ('follower') o seguidos ('following').

    Cada item de Apify trae: userId, username, fullName, profilePicUrl,
    isVerified, isPrivate, type.
    """
    rtype = "follower" if relation_type in ("followers", "follower") else "following"
    conn = _connect()
    count = 0
    for item in items:
        user_id = str(item.get("userId") or item.get("username") or "")
        if not user_id:
            continue
        conn.execute(
            """
            INSERT INTO relation_history(
                captured_at, user_id, relation_type, username,
                full_name, profile_pic_url, is_verified, is_private
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                captured_at,
                user_id,
                rtype,
                item.get("username"),
                item.get("fullName"),
                item.get("profilePicUrl"),
                1 if item.get("isVerified") else 0,
                1 if item.get("isPrivate") else 0,
            ),
        )
        count += 1
    _close(conn)
    return count


# --- Lectura -----------------------------------------------------------------

def _rows(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = _connect()
    cur = conn.execute(sql, params)
    cols = [d[0] for d in (cur.description or [])]
    data = []
    for r in cur.fetchall():
        if isinstance(r, dict):
            data.append(dict(r))
        else:
            data.append(dict(zip(cols, r)))
    _close(conn)
    return data


def _parse_list(value: Any) -> List:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def get_profile_history() -> List[Dict[str, Any]]:
    return _rows("SELECT * FROM profile_history ORDER BY captured_at ASC")


def get_latest_profile() -> Optional[Dict[str, Any]]:
    rows = _rows("SELECT * FROM profile_history ORDER BY captured_at DESC LIMIT 1")
    return rows[0] if rows else None


def get_posts() -> List[Dict[str, Any]]:
    """Publicaciones normalizadas al esquema camelCase del Actor (igual que
    los datos crudos de Apify) para que la analítica sea consistente."""
    rows = _rows("SELECT * FROM posts ORDER BY published_at DESC")
    normalized = []
    for r in rows:
        normalized.append({
            "id": r.get("post_id"),
            "shortCode": r.get("short_code"),
            "url": r.get("url"),
            "caption": r.get("caption"),
            "type": r.get("type"),
            "productType": r.get("product_type"),
            "likesCount": r.get("likes_count"),
            "commentsCount": r.get("comments_count"),
            "videoViewCount": r.get("video_view_count"),
            "videoPlayCount": r.get("video_play_count"),
            "timestamp": r.get("published_at"),
            "displayUrl": r.get("display_url"),
            "isPinned": bool(r.get("is_pinned")),
            "hashtags": _parse_list(r.get("hashtags")),
            "mentions": _parse_list(r.get("mentions")),
            "firstCapturedAt": r.get("first_captured_at"),
            "lastCapturedAt": r.get("last_captured_at"),
        })
    return normalized


def get_post_raw(post_id: str) -> Optional[Dict[str, Any]]:
    rows = _rows("SELECT raw_json FROM posts WHERE post_id = ?", (post_id,))
    if not rows or not rows[0].get("raw_json"):
        return None
    try:
        return json.loads(rows[0]["raw_json"])
    except (TypeError, ValueError):
        return None


def get_post_history() -> List[Dict[str, Any]]:
    return _rows("SELECT * FROM post_history ORDER BY captured_at ASC")


def get_relation_history() -> List[Dict[str, Any]]:
    return _rows("SELECT * FROM relation_history ORDER BY captured_at ASC")


def get_relation_dates(relation_type: str) -> List[str]:
    rows = _rows(
        "SELECT DISTINCT captured_at FROM relation_history"
        " WHERE relation_type = ? ORDER BY captured_at ASC",
        (relation_type,),
    )
    return [r["captured_at"] for r in rows]


def get_relations_at(relation_type: str, captured_at: str) -> List[Dict[str, Any]]:
    return _rows(
        "SELECT * FROM relation_history WHERE relation_type = ? AND captured_at = ?",
        (relation_type, captured_at),
    )


def get_runs() -> List[Dict[str, Any]]:
    return _rows("SELECT * FROM runs ORDER BY id DESC LIMIT 50")


# --- Eventos de cambios (historial de altas/bajas) ---------------------------

def save_relation_events(events: Iterable[Dict[str, Any]]) -> int:
    """Inserta eventos de cambio (unfollows, nuevos seguidores, etc.).

    Usa INSERT OR IGNORE para ser idempotente: no se duplica el mismo evento
    para la misma fecha.
    """
    conn = _connect()
    inserted = 0
    for e in events:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO relation_events(
                event_type, relation_type, user_id, username, full_name,
                profile_pic_url, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                e.get("event_type"),
                e.get("relation_type"),
                e.get("user_id"),
                e.get("username"),
                e.get("full_name"),
                e.get("profile_pic_url"),
                e.get("detected_at"),
            ),
        )
        inserted += cur.rowcount
    _close(conn)
    return inserted


def get_relation_events() -> List[Dict[str, Any]]:
    return _rows("SELECT * FROM relation_events ORDER BY detected_at DESC, id DESC")


# --- Comentarios -------------------------------------------------------------

def save_comments(items: Iterable[Dict[str, Any]], captured_at: str) -> int:
    conn = _connect()
    count = 0
    for c in items:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        post_url = c.get("postUrl") or ""
        # extraer shortCode del postUrl si está disponible
        post_id = ""
        if "/p/" in post_url:
            post_id = post_url.split("/p/")[-1].split("/")[0]
        elif "/reel/" in post_url:
            post_id = post_url.split("/reel/")[-1].split("/")[0]
        owner = c.get("owner") or {}
        conn.execute(
            """
            INSERT OR REPLACE INTO comments(
                id, post_id, post_url, text, owner_username, owner_id,
                likes_count, timestamp, captured_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cid,
                post_id,
                post_url,
                c.get("text"),
                c.get("ownerUsername") or owner.get("username"),
                c.get("ownerId") or owner.get("id"),
                c.get("likesCount"),
                c.get("timestamp"),
                captured_at,
                json.dumps(c, ensure_ascii=False),
            ),
        )
        count += 1
    _close(conn)
    return count


def get_comments() -> List[Dict[str, Any]]:
    return _rows("SELECT * FROM comments ORDER BY timestamp DESC")


# --- Menciones ---------------------------------------------------------------

def save_mentions(items: Iterable[Dict[str, Any]], captured_at: str) -> int:
    conn = _connect()
    count = 0
    for m in items:
        mid = str(m.get("id") or m.get("shortCode") or m.get("url") or "")
        if not mid:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO mentions(
                id, short_code, url, caption, owner_username,
                timestamp, likes_count, captured_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mid,
                m.get("shortCode"),
                m.get("url"),
                m.get("caption"),
                m.get("ownerUsername"),
                m.get("timestamp"),
                m.get("likesCount"),
                captured_at,
                json.dumps(m, ensure_ascii=False),
            ),
        )
        count += 1
    _close(conn)
    return count


def get_mentions() -> List[Dict[str, Any]]:
    return _rows("SELECT * FROM mentions ORDER BY timestamp DESC")


def has_data() -> bool:
    conn = _connect()
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='profile_history'"
    ).fetchone()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM profile_history"
    ).fetchone() if exists else None
    n = row[0] if row else 0
    _close(conn)
    return n > 0

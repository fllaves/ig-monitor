"""Analítica del centro de monitoreo.

Contiene funciones puras (sin dependencias de Streamlit) que transforman los
datos crudos en métricas y figuras de Plotly. `plotly` se importa de forma
opcional para poder ejecutar la lógica pura sin él.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import plotly.graph_objects as go
    _HAS_PLOTLY = True
except Exception:  # pragma: no cover - sólo para entornos sin plotly
    go = None
    _HAS_PLOTLY = False

DEFAULT_COLOR = "#6366f1"  # índigo
GREEN = "#22c55e"
AMBER = "#f59e0b"
RED = "#ef4444"
PALETTE = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#a855f7"]


# --- Utilidades --------------------------------------------------------------

def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        s = value.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def content_type(post: Dict) -> str:
    pt = (post.get("productType") or "").lower()
    t = (post.get("type") or "").lower()
    if pt == "clips":
        return "Reel"
    if t == "sidecar":
        return "Carrusel"
    if t == "video":
        return "Video"
    return "Foto"


def _engagement_rate(post: Dict, followers: int) -> float:
    if not followers:
        return 0.0
    likes = post.get("likesCount") or 0
    comments = post.get("commentsCount") or 0
    return (likes + comments) / followers * 100


def enrich_posts(posts: List[Dict], followers: int) -> List[Dict]:
    out = []
    for p in posts:
        d = dict(p)
        d["content_type"] = content_type(p)
        dt = _parse_dt(p.get("published_at") or p.get("timestamp"))
        d["dt"] = dt
        d["hour"] = dt.hour if dt else None
        d["weekday"] = dt.strftime("%a") if dt else None
        d["engagement_rate"] = round(_engagement_rate(p, followers), 3)
        d["hashtag_list"] = p.get("hashtags") or []
        out.append(d)
    out.sort(key=lambda x: (x.get("dt") or datetime.min), reverse=True)
    return out


# --- KPIs --------------------------------------------------------------------

def compute_kpis(posts: List[Dict], latest_profile: Optional[Dict],
                 prev_profile: Optional[Dict]) -> Dict[str, Any]:
    followers = (latest_profile or {}).get("followers_count") or 0
    prev_followers = (prev_profile or {}).get("followers_count") or 0

    likes = [p.get("likesCount") or 0 for p in posts if p.get("likesCount") not in (None, -1)]
    comments = [p.get("commentsCount") or 0 for p in posts]

    def avg(vals):
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    return {
        "followers": followers,
        "followers_delta": followers - prev_followers if prev_followers else None,
        "following": (latest_profile or {}).get("follows_count"),
        "posts": (latest_profile or {}).get("posts_count") or len(posts),
        "avg_likes": avg(likes),
        "avg_comments": avg(comments),
        "avg_engagement_rate": round(avg(
            [_engagement_rate(p, followers) for p in posts]
        ), 3),
        "total_likes": sum(likes),
        "total_comments": sum(comments),
    }


# --- Series para gráficos ----------------------------------------------------

def follower_series(history: List[Dict]) -> List[Dict]:
    series = []
    for h in history:
        dt = _parse_dt(h.get("captured_at"))
        series.append({
            "dt": dt,
            "followers": h.get("followers_count"),
            "following": h.get("follows_count"),
        })
    return [s for s in series if s["dt"] is not None and s["followers"] is not None]


def posts_over_time(posts: List[Dict], bucket: str = "month") -> List[Dict]:
    buckets = Counter()
    for p in posts:
        dt = p.get("dt")
        if not dt:
            continue
        key = dt.strftime("%Y-%m-%d") if bucket == "day" else dt.strftime("%Y-%m")
        buckets[key] += 1
    return [{"period": k, "count": v} for k, v in sorted(buckets.items())]


def hour_distribution(posts: List[Dict]) -> List[Dict]:
    c = Counter()
    for p in posts:
        if p.get("hour") is not None:
            c[p["hour"]] += 1
    return [{"hour": h, "count": c.get(h, 0)} for h in range(24)]


def content_type_distribution(posts: List[Dict]) -> List[Dict]:
    c = Counter(p.get("content_type", "Foto") for p in posts)
    order = ["Reel", "Foto", "Carrusel", "Video"]
    return [{"type": k, "count": c.get(k, 0)} for k in order if c.get(k, 0)]


def hashtag_frequency(posts: List[Dict], top_n: int = 15) -> List[Dict]:
    c = Counter()
    for p in posts:
        for h in p.get("hashtag_list", []) or []:
            tag = h.lstrip("#").lower()
            if tag:
                c[tag] += 1
    return [{"hashtag": k, "count": v} for k, v in c.most_common(top_n)]


def top_posts(posts: List[Dict], n: int = 10, metric: str = "likes") -> List[Dict]:
    key = "likesCount" if metric == "likes" else "commentsCount"
    valid = [p for p in posts if p.get(key) not in (None, -1)]
    valid.sort(key=lambda x: x.get(key) or 0, reverse=True)
    return valid[:n]


# --- Seguidores / seguidos ----------------------------------------------------

def _rel_key(row: Dict) -> str:
    """Clave de identidad para comparar listas de distinta fuente.

    Empareja por username (en minúsculas), que es lo único que comparten el
    snapshot histórico y los datos de Apify; si no hay username, usa user_id.
    """
    username = (row.get("username") or "").strip().lower()
    return username or str(row.get("user_id") or "")


def relation_counts_series(history: List[Dict]) -> List[Dict]:
    """Tamaño de las listas de seguidores y seguidos en cada fecha capturada."""
    dates = sorted({h["captured_at"] for h in history})
    series = []
    for d in dates:
        followers = sum(1 for h in history if h["captured_at"] == d and h["relation_type"] == "follower")
        following = sum(1 for h in history if h["captured_at"] == d and h["relation_type"] == "following")
        series.append({
            "dt": _parse_dt(d),
            "followers": followers,
            "following": following,
        })
    return [s for s in series if s["dt"] is not None]


def relation_delta(history: List[Dict], relation_type: str) -> Optional[Dict[str, Any]]:
    """Compara las dos últimas fechas para detectar altas y bajas."""
    rows = [h for h in history if h["relation_type"] == relation_type]
    dates = sorted({h["captured_at"] for h in rows})
    if len(dates) < 2:
        return None

    prev_date, latest_date = dates[-2], dates[-1]
    prev_ids = {_rel_key(h) for h in rows if h["captured_at"] == prev_date}
    latest_ids = {_rel_key(h) for h in rows if h["captured_at"] == latest_date}

    info: Dict[str, Dict] = {}
    for h in rows:
        key = _rel_key(h)
        if key not in info:
            info[key] = h

    def describe(uid: str) -> Dict[str, Any]:
        h = info.get(uid, {})
        return {
            "user_id": uid,
            "username": h.get("username"),
            "full_name": h.get("full_name"),
            "profile_pic_url": h.get("profile_pic_url"),
            "is_verified": bool(h.get("is_verified")),
            "is_private": bool(h.get("is_private")),
        }

    return {
        "relation_type": relation_type,
        "prev_date": prev_date,
        "latest_date": latest_date,
        "prev_count": len(prev_ids),
        "latest_count": len(latest_ids),
        "net": len(latest_ids) - len(prev_ids),
        "new": [describe(u) for u in sorted(latest_ids - prev_ids)],
        "lost": [describe(u) for u in sorted(prev_ids - latest_ids)],
    }


def build_relation_events(relation_history: List[Dict]) -> List[Dict]:
    """Convierte altas/bajas detectadas en eventos persistentes para el historial."""
    events = []
    mapping = [
        ("follower", "new_follower", "lost_follower"),
        ("following", "new_following", "lost_following"),
    ]
    for rtype, new_type, lost_type in mapping:
        delta = relation_delta(relation_history, rtype)
        if not delta:
            continue
        for acc in delta["new"]:
            events.append({
                "event_type": new_type, "relation_type": rtype,
                "user_id": acc["user_id"], "username": acc["username"],
                "full_name": acc["full_name"], "profile_pic_url": acc["profile_pic_url"],
                "detected_at": delta["latest_date"],
            })
        for acc in delta["lost"]:
            events.append({
                "event_type": lost_type, "relation_type": rtype,
                "user_id": acc["user_id"], "username": acc["username"],
                "full_name": acc["full_name"], "profile_pic_url": acc["profile_pic_url"],
                "detected_at": delta["latest_date"],
            })
    return events


def relation_members(history: List[Dict], relation_type: str) -> List[Dict]:
    """Miembros actuales de una lista, con primera y última fecha vistas."""
    rows = [h for h in history if h["relation_type"] == relation_type]
    dates = sorted({h["captured_at"] for h in rows})
    if not dates:
        return []
    latest = dates[-1]
    current_ids = {_rel_key(h) for h in rows if h["captured_at"] == latest}

    members: Dict[str, Dict] = {}
    for h in rows:
        key = _rel_key(h)
        if key not in current_ids:
            continue
        m = members.setdefault(key, dict(h))
        m["first_seen"] = min(m.get("first_seen") or h["captured_at"], h["captured_at"])
        m["last_seen"] = max(m.get("last_seen") or h["captured_at"], h["captured_at"])
        m["is_verified"] = bool(m.get("is_verified"))
        m["is_private"] = bool(m.get("is_private"))

    result = list(members.values())
    result.sort(key=lambda x: (x.get("username") or "").lower())
    return result


# --- Mutuales ----------------------------------------------------------------

def compute_mutuals(relation_history: List[Dict]) -> Dict[str, List[Dict]]:
    """Cruza seguidores y seguidos para hallar mutuos y no recíprocos."""
    followers = {_rel_key(m) for m in relation_members(relation_history, "follower")}
    following = {_rel_key(m) for m in relation_members(relation_history, "following")}

    info: Dict[str, Dict] = {}
    for h in relation_history:
        info.setdefault(_rel_key(h), h)

    def describe(uid: str) -> Dict[str, Any]:
        h = info.get(uid, {})
        return {
            "user_id": uid,
            "username": h.get("username"),
            "full_name": h.get("full_name"),
            "profile_pic_url": h.get("profile_pic_url"),
            "is_verified": bool(h.get("is_verified")),
            "is_private": bool(h.get("is_private")),
        }

    mutuals = sorted(followers & following)
    not_followed_back = sorted(following - followers)   # sigues pero no te siguen
    not_following_back = sorted(followers - following)  # te siguen pero no les sigues

    return {
        "mutuals": [describe(u) for u in mutuals],
        "not_followed_back": [describe(u) for u in not_followed_back],
        "not_following_back": [describe(u) for u in not_following_back],
    }


# --- Categorías --------------------------------------------------------------

def category_distribution(members: List[Dict], profiles: Dict[str, Dict],
                          top_n: int = 20) -> List[Dict]:
    """Cuenta miembros por categoría (perfil enriquecido o heurística)."""
    from categorize import category_for

    counts: Counter = Counter()
    for m in members:
        key = _rel_key(m)
        prof = profiles.get(key) or {}
        cat = prof.get("category")
        if not cat:
            cat = category_for(m.get("username"), m.get("full_name"))
        counts[cat] += 1
    return [{"category": k, "count": v} for k, v in counts.most_common(top_n)]


# --- Retención y churn -------------------------------------------------------

def follow_retention(history: List[Dict], relation_type: str = "following") -> Optional[Dict]:
    """De las cuentas de la PRIMERA foto, cuántas siguen en la ÚLTIMA."""
    rows = [h for h in history if h["relation_type"] == relation_type]
    dates = sorted({h["captured_at"] for h in rows})
    if len(dates) < 2:
        return None
    first, latest = dates[0], dates[-1]
    first_ids = {_rel_key(h) for h in rows if h["captured_at"] == first}
    latest_ids = {_rel_key(h) for h in rows if h["captured_at"] == latest}
    retained = len(first_ids & latest_ids)
    return {
        "relation_type": relation_type,
        "first_date": first,
        "latest_date": latest,
        "first_count": len(first_ids),
        "latest_count": len(latest_ids),
        "retained": retained,
        "dropped": len(first_ids - latest_ids),
        "added": len(latest_ids - first_ids),
        "retention_pct": round(retained / len(first_ids) * 100, 1) if first_ids else 0.0,
    }


def _events_by_account(events: List[Dict]) -> Dict[str, List[Dict]]:
    grouped: Dict[str, List[Dict]] = {}
    for e in events or []:
        key = (e.get("username") or "").strip().lower() or str(e.get("user_id") or "")
        if key:
            grouped.setdefault(key, []).append(e)
    return grouped


def relation_churn(events: List[Dict], min_events: int = 2) -> List[Dict]:
    """Cuentas con más movimiento (serial follow/unfollow)."""
    out = []
    for key, evs in _events_by_account(events).items():
        lost = [e for e in evs if str(e.get("event_type", "")).startswith("lost")]
        new = [e for e in evs if str(e.get("event_type", "")).startswith("new")]
        if len(evs) < min_events and not (lost and new):
            continue
        out.append({
            "username": evs[-1].get("username") or key,
            "full_name": evs[-1].get("full_name"),
            "lost_count": len(lost),
            "new_count": len(new),
            "total": len(evs),
            "last_event": max((e.get("detected_at") or "") for e in evs),
        })
    out.sort(key=lambda x: (-x["total"], x["username"] or ""))
    return out


def re_follows(events: List[Dict]) -> List[Dict]:
    """Cuentas con patrón baja → alta (volviste a seguir / te volvió a seguir)."""
    out = []
    for key, evs in _events_by_account(events).items():
        ordered = sorted(evs, key=lambda e: e.get("detected_at") or "")
        seen_lost = False
        cycle = False
        for e in ordered:
            t = str(e.get("event_type", ""))
            if t.startswith("lost"):
                seen_lost = True
            elif t.startswith("new") and seen_lost:
                cycle = True
        if cycle:
            out.append({
                "username": ordered[-1].get("username") or key,
                "full_name": ordered[-1].get("full_name"),
                "eventos": len(ordered),
                "ultimo": ordered[-1].get("detected_at"),
            })
    out.sort(key=lambda x: x.get("ultimo") or "", reverse=True)
    return out


def unfollow_anomalies(events: List[Dict]) -> List[Dict]:
    """Bajas por fecha, marcando picos anómalos."""
    lost = [e for e in events or [] if str(e.get("event_type", "")).startswith("lost")]
    by_date = Counter((e.get("detected_at") or "")[:10] for e in lost)
    if not by_date:
        return []
    values = list(by_date.values())
    avg = sum(values) / len(values)
    rows = [{"date": d, "count": c,
             "is_spike": c > max(5, avg * 2)} for d, c in sorted(by_date.items())]
    return rows


# --- Ficha 360 ---------------------------------------------------------------

def account_card(history: List[Dict], events: List[Dict], profiles: Dict[str, Dict],
                 identifier: str) -> Dict[str, Any]:
    """Todo lo que sabemos de una cuenta concreta."""
    key = str(identifier).strip().lstrip("@").lower()
    followers = {_rel_key(m) for m in relation_members(history, "follower")}
    following = {_rel_key(m) for m in relation_members(history, "following")}
    rows = [h for h in history if _rel_key(h) == key]
    info = rows[-1] if rows else {}
    prof = profiles.get(key) or {}
    evs = [e for e in (events or [])
           if (e.get("username") or "").strip().lower() == key]
    username = info.get("username") or prof.get("username") or identifier

    return {
        "username": username,
        "full_name": info.get("full_name") or prof.get("full_name"),
        "biography": prof.get("biography"),
        "category": prof.get("category"),
        "is_follower": key in followers,
        "is_following": key in following,
        "mutual": key in followers and key in following,
        "first_seen": min((h["captured_at"] for h in rows), default=None),
        "last_seen": max((h["captured_at"] for h in rows), default=None),
        "snapshots": len({h["captured_at"] for h in rows}),
        "events": sorted(evs, key=lambda e: e.get("detected_at") or "", reverse=True),
        "profile_url": f"https://www.instagram.com/{username}/",
        "enriched": bool(prof),
        "profile_followers": prof.get("followers_count"),
        "profile_posts": prof.get("posts_count"),
        "verified": bool(prof.get("is_verified")) if prof else None,
        "private": bool(prof.get("is_private")) if prof else None,
        "latest_posts": _parse_latest(prof.get("latest_posts_json")),
    }


def _parse_latest(value) -> List[Dict]:
    if not value:
        return []
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


def account_report(history: List[Dict], events: List[Dict], posts: List[Dict],
                   comments: List[Dict], mentions: List[Dict],
                   profiles: Dict[str, Dict], identifier: str) -> Dict[str, Any]:
    """Ficha completa con TODAS las señales sociales disponibles de una cuenta."""
    key = str(identifier).strip().lstrip("@").lower()
    card = account_card(history, events, profiles, identifier)

    my_mentions = []
    for p in posts or []:
        tags = [(m or "").strip().lstrip("@").lower() for m in (p.get("mentions") or [])]
        if key in tags:
            my_mentions.append({
                "date": (p.get("timestamp") or "")[:10],
                "text": (p.get("caption") or "").replace("\n", " ")[:160],
                "url": p.get("url") or "",
            })

    their_mentions = []
    for m in mentions or []:
        if (m.get("owner_username") or "").strip().lower() == key:
            their_mentions.append({
                "date": (m.get("timestamp") or "")[:10],
                "text": (m.get("caption") or "").replace("\n", " ")[:160],
                "url": m.get("url") or "",
            })

    their_comments = []
    for c in comments or []:
        if (c.get("owner_username") or "").strip().lower() == key:
            their_comments.append({
                "date": (c.get("timestamp") or "")[:10],
                "text": (c.get("text") or "").replace("\n", " ")[:160],
                "post": c.get("post_id") or "",
            })

    timeline = []
    for e in card["events"]:
        timeline.append({"date": (e.get("detected_at") or "")[:10],
                         "what": e.get("event_type"), "detail": ""})
    for m in my_mentions:
        timeline.append({"date": m["date"], "what": "yo_la_menciono", "detail": m["text"]})
    for m in their_mentions:
        timeline.append({"date": m["date"], "what": "me_menciona", "detail": m["text"]})
    for c in their_comments:
        timeline.append({"date": c["date"], "what": "me_comenta", "detail": c["text"]})
    timeline.sort(key=lambda x: x["date"] or "", reverse=True)

    card.update({
        "my_mentions": my_mentions,
        "their_mentions": their_mentions,
        "their_comments": their_comments,
        "timeline": timeline,
        "total_signals": (len(card["events"]) + len(my_mentions)
                          + len(their_mentions) + len(their_comments)),
    })
    return card


def watch_interactions(external_posts: List[Dict], external_comments: List[Dict],
                       my_post_comments: List[Dict], watched: str,
                       me: str, story_mentions: List[Dict] = None) -> Dict[str, Any]:
    """Interacciones públicas entre 'me' y una cuenta destacada."""
    w = str(watched).strip().lstrip("@").lower()
    me_key = (me or "").strip().lstrip("@").lower()

    def owner(row) -> str:
        return (row.get("owner_username") or "").strip().lstrip("@").lower()

    their_posts = [p for p in (external_posts or [])
                   if (p.get("source_username") or "").strip().lower() == w]

    ext = external_comments or []
    my_comments_on_theirs = [c for c in ext
                             if (c.get("source_username") or "").strip().lower() == w
                             and owner(c) == me_key]
    their_comments = [c for c in ext if owner(c) == w]
    their_comments_on_mine = [c for c in (my_post_comments or []) if owner(c) == w]

    sm = story_mentions or []
    stories_from_them = [s for s in sm
                         if (s.get("source_username") or "").strip().lower() == w]
    stories_of_me = [s for s in sm
                     if (s.get("mentioned_username") or "").strip().lower() == w]

    dates = [(c.get("timestamp") or "") for c in (my_comments_on_theirs + their_comments_on_mine)
             if c.get("timestamp")]
    dates += [(s.get("timestamp") or "") for s in (stories_from_them + stories_of_me)
              if s.get("timestamp")]
    return {
        "their_posts": their_posts,
        "my_comments_on_theirs": my_comments_on_theirs,
        "their_comments_on_mine": their_comments_on_mine,
        "their_comments": their_comments,
        "stories_from_them": stories_from_them,
        "stories_of_me": stories_of_me,
        "total": (len(my_comments_on_theirs) + len(their_comments_on_mine)
                  + len(their_comments) + len(stories_from_them) + len(stories_of_me)),
        "oldest": min(dates) if dates else "",
        "newest": max(dates) if dates else "",
    }


# --- Historial de interacciones ----------------------------------------------

def interaction_index(history: List[Dict], events: List[Dict], posts: List[Dict],
                      comments: List[Dict], mentions: List[Dict],
                      exclude: Iterable[str] = ()) -> List[Dict]:
    """Índice de interacciones por cuenta combinando señales públicas.

    Señales incluidas: follows/unfollows, menciones que haces en tus captions,
    menciones que te hacen y comentarios que recibes en tus publicaciones.
    """
    excluded = {str(x).strip().lstrip("@").lower() for x in exclude if x}
    idx: Dict[str, Dict] = {}

    def entry(name) -> Optional[Dict]:
        key = (str(name) if name else "").strip().lstrip("@").lower()
        if not key or key in excluded:
            return None
        return idx.setdefault(key, {
            "key": key,
            "username": str(name).strip().lstrip("@"),
            "follow_events": 0,
            "mentioned_by_me": 0,
            "mentions_me": 0,
            "comments_received": 0,
            "last": "",
        })

    for e in events or []:
        d = entry(e.get("username") or e.get("user_id"))
        if d is None:
            continue
        d["follow_events"] += 1
        d["last"] = max(d["last"], (e.get("detected_at") or "")[:10])

    for p in posts or []:
        for m in (p.get("mentions") or []):
            d = entry(m)
            if d is None:
                continue
            d["mentioned_by_me"] += 1

    for m in mentions or []:
        d = entry(m.get("owner_username"))
        if d is None:
            continue
        d["mentions_me"] += 1
        d["last"] = max(d["last"], (m.get("timestamp") or "")[:10])

    for c in comments or []:
        d = entry(c.get("owner_username"))
        if d is None:
            continue
        d["comments_received"] += 1
        d["last"] = max(d["last"], (c.get("timestamp") or "")[:10])

    out = []
    for v in idx.values():
        v["total"] = (v["follow_events"] + v["mentioned_by_me"]
                      + v["mentions_me"] + v["comments_received"])
        if v["total"] > 0:
            out.append(v)
    out.sort(key=lambda x: (-x["total"], x["username"].lower()))
    return out


# --- Limpieza ----------------------------------------------------------------

def cleaning_suggestions(relation_history: List[Dict]) -> List[Dict]:
    """Cuentas que sigues y no te siguen de vuelta (candidatas a limpiar)."""
    return compute_mutuals(relation_history)["not_followed_back"]


# --- Calidad de audiencia ----------------------------------------------------

def audience_quality(members: List[Dict]) -> Dict[str, Any]:
    total = len(members)
    if not total:
        return {"total": 0, "verified": 0, "private": 0, "no_name": 0,
                "no_pic": 0, "suspicious": 0}
    verified = sum(1 for m in members if m.get("is_verified"))
    private = sum(1 for m in members if m.get("is_private"))
    no_name = sum(1 for m in members if not (m.get("full_name") or "").strip())
    no_pic = sum(1 for m in members if not (m.get("profile_pic_url") or "").strip())
    suspicious = sum(1 for m in members
                     if not (m.get("full_name") or "").strip()
                     and not (m.get("profile_pic_url") or "").strip())
    return {
        "total": total,
        "verified": verified,
        "private": private,
        "no_name": no_name,
        "no_pic": no_pic,
        "suspicious": suspicious,
    }


# --- Comentarios y sentimiento -----------------------------------------------

_POSITIVE = ["gracias", "genial", "excelente", "buen", "buena", "me encanta",
             "increíble", "felicidades", "crack", "top", "amo", "love", "great",
             "nice", "🔥", "👏", "❤️", "💪", "🤩", "🙌", "👍", "😍", "wow",
             "brutal", "tremendo", "excelente", "motiv", "inspir", "aprend",
             "claridad", "grande", "ídolo", "idolo", "maestro", "crack"]
_NEGATIVE = ["mal", "malo", "mala", "pésimo", "horrible", "no me gusta", "asco",
             "estafa", "basura", "mentira", "falso", "👎", "😡", "🤮", "aburri",
             "pésimo", "decepci", "mala onda"]


def sentiment(text: Optional[str]) -> str:
    t = (text or "").lower()
    pos = sum(1 for w in _POSITIVE if w in t)
    neg = sum(1 for w in _NEGATIVE if w in t)
    if pos > neg:
        return "positivo"
    if neg > pos:
        return "negativo"
    return "neutral"


def comment_stats(comments: List[Dict]) -> Dict[str, Any]:
    total = len(comments)
    sent = Counter(sentiment(c.get("text")) for c in comments)
    commenters = Counter(c.get("owner_username") for c in comments if c.get("owner_username"))
    return {
        "total": total,
        "positive": sent.get("positivo", 0),
        "negative": sent.get("negativo", 0),
        "neutral": sent.get("neutral", 0),
        "top_commenters": [{"username": k, "count": v}
                           for k, v in commenters.most_common(10)],
    }


# --- Figuras Plotly ----------------------------------------------------------

def _need_plotly():
    if not _HAS_PLOTLY:
        raise RuntimeError("plotly no está instalado")


def fig_followers(series: List[Dict]) -> go.Figure:
    _need_plotly()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[s["dt"] for s in series],
        y=[s["followers"] for s in series],
        mode="lines+markers",
        name="Seguidores",
        line=dict(color=DEFAULT_COLOR, width=3),
        fill="tozeroy",
        hovertemplate="%{x|%d %b %Y}<br>%{y:,} seguidores<extra></extra>",
    ))
    fig.update_layout(
        title="Crecimiento de seguidores",
        xaxis_title="Fecha",
        yaxis_title="Seguidores",
        margin=dict(t=40, b=40),
        hovermode="x unified",
        template="plotly_white",
    )
    return fig


def fig_posts_over_time(data: List[Dict]) -> go.Figure:
    _need_plotly()
    fig = go.Figure(go.Bar(
        x=[d["period"] for d in data],
        y=[d["count"] for d in data],
        marker_color=DEFAULT_COLOR,
        hovertemplate="%{x}<br>%{y} publicaciones<extra></extra>",
    ))
    fig.update_layout(
        title="Publicaciones por mes",
        xaxis_title="Mes",
        yaxis_title="Publicaciones",
        margin=dict(t=40, b=40),
        template="plotly_white",
    )
    return fig


def fig_hour_distribution(data: List[Dict]) -> go.Figure:
    _need_plotly()
    fig = go.Figure(go.Bar(
        x=[f"{d['hour']:02d}:00" for d in data],
        y=[d["count"] for d in data],
        marker_color=GREEN,
        hovertemplate="%{x}<br>%{y} publicaciones<extra></extra>",
    ))
    fig.update_layout(
        title="Horario de publicación (hora del día, UTC)",
        xaxis_title="Hora",
        yaxis_title="Publicaciones",
        margin=dict(t=40, b=40),
        template="plotly_white",
    )
    return fig


def fig_content_type(data: List[Dict]) -> go.Figure:
    _need_plotly()
    labels = [d["type"] for d in data]
    values = [d["count"] for d in data]
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.45,
        marker=dict(colors=PALETTE[:len(labels)]),
        textinfo="label+percent",
    ))
    fig.update_layout(title="Tipo de contenido", margin=dict(t=40, b=20), template="plotly_white")
    return fig


def fig_hashtags(data: List[Dict]) -> go.Figure:
    _need_plotly()
    fig = go.Figure(go.Bar(
        x=[d["count"] for d in data],
        y=[f"#{d['hashtag']}" for d in data],
        orientation="h",
        marker_color="#a855f7",
        hovertemplate="#%{y}<br>%{x} usos<extra></extra>",
    ))
    fig.update_layout(
        title="Hashtags más usados",
        xaxis_title="Usos",
        yaxis=dict(autorange="reversed"),
        margin=dict(t=40, b=20),
        template="plotly_white",
    )
    return fig


def fig_top_posts(data: List[Dict], metric: str = "likes") -> go.Figure:
    _need_plotly()
    key = "likesCount" if metric == "likes" else "commentsCount"
    labels = []
    for p in data:
        cap = (p.get("caption") or "").strip().replace("\n", " ")
        cap = cap[:40] + "…" if len(cap) > 40 else cap
        labels.append(cap or p.get("shortCode", "?"))
    values = [p.get(key) or 0 for p in data]
    fig = go.Figure(go.Bar(
        x=values,
        y=labels,
        orientation="h",
        marker_color=DEFAULT_COLOR,
        hovertemplate="%{y}<br>%{x:,}<extra></extra>",
    ))
    metric_name = "likes" if metric == "likes" else "comentarios"
    fig.update_layout(
        title=f"Top publicaciones por {metric_name}",
        xaxis_title=metric_name.capitalize(),
        yaxis=dict(autorange="reversed"),
        margin=dict(t=40, b=20),
        template="plotly_white",
    )
    return fig


def fig_engagement_scatter(posts: List[Dict]) -> go.Figure:
    _need_plotly()
    x = [p.get("likesCount") or 0 for p in posts]
    y = [p.get("commentsCount") or 0 for p in posts]
    fig = go.Figure(go.Scatter(
        x=x, y=y, mode="markers",
        marker=dict(color=DEFAULT_COLOR, size=9, opacity=0.7),
        text=[p.get("shortCode") or "" for p in posts],
        hovertemplate="%{text}<br>%{x:,} likes · %{y:,} comentarios<extra></extra>",
    ))
    fig.update_layout(
        title="Likes vs. comentarios por publicación",
        xaxis_title="Likes",
        yaxis_title="Comentarios",
        margin=dict(t=40, b=40),
        template="plotly_white",
    )
    return fig


def fig_relation_counts(series: List[Dict]) -> go.Figure:
    _need_plotly()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[s["dt"] for s in series],
        y=[s["followers"] for s in series],
        mode="lines+markers",
        name="Seguidores (lista)",
        line=dict(color=DEFAULT_COLOR, width=3),
    ))
    fig.add_trace(go.Scatter(
        x=[s["dt"] for s in series],
        y=[s["following"] for s in series],
        mode="lines+markers",
        name="Seguidos (lista)",
        line=dict(color=GREEN, width=3),
    ))
    fig.update_layout(
        title="Tamaño de las listas a lo largo del tiempo",
        xaxis_title="Fecha",
        yaxis_title="Cuentas",
        margin=dict(t=40, b=40),
        hovermode="x unified",
        template="plotly_white",
    )
    return fig


def fig_relation_flow(deltas: List[Dict]) -> go.Figure:
    """Barras de altas vs. bajas para seguidores y seguidos."""
    _need_plotly()
    labels = []
    new_vals = []
    lost_vals = []
    for d in deltas:
        pretty = "Seguidores" if d["relation_type"] == "follower" else "Seguidos"
        labels.append(pretty)
        new_vals.append(len(d["new"]))
        lost_vals.append(-len(d["lost"]))
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=new_vals, name="Nuevos", marker_color=GREEN))
    fig.add_trace(go.Bar(x=labels, y=lost_vals, name="Bajas", marker_color=RED))
    fig.update_layout(
        title="Cambios desde la última sincronización",
        yaxis_title="Cuentas (bajas en negativo)",
        barmode="relative",
        margin=dict(t=40, b=40),
        template="plotly_white",
    )
    return fig


def fig_sentiment(stats: Dict[str, Any]) -> go.Figure:
    """Donut de sentimiento de los comentarios."""
    _need_plotly()
    labels = ["Positivos", "Neutrales", "Negativos"]
    values = [stats.get("positive", 0), stats.get("neutral", 0), stats.get("negative", 0)]
    colors = [GREEN, "#94a3b8", RED]
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.5,
        marker=dict(colors=colors),
        textinfo="label+percent",
    ))
    fig.update_layout(title="Sentimiento de comentarios", margin=dict(t=40, b=20), template="plotly_white")
    return fig


def fig_categories(data: List[Dict], top_n: int = 12) -> go.Figure:
    """Donut de categorías de las cuentas."""
    _need_plotly()
    rows = data[:top_n]
    labels = [d["category"] for d in rows]
    values = [d["count"] for d in rows]
    fig = go.Figure(go.Pie(
        labels=labels, values=values, hole=0.45,
        marker=dict(colors=(PALETTE * 3)[:len(labels)]),
        textinfo="label+percent",
    ))
    fig.update_layout(title="Categorías de las cuentas",
                      margin=dict(t=40, b=20), template="plotly_white")
    return fig


def fig_retention(retentions: List[Dict]) -> go.Figure:
    """Barras de retención (se mantienen / se perdieron / nuevas)."""
    _need_plotly()
    labels, retained, dropped, added = [], [], [], []
    for r in retentions:
        labels.append("Seguidores" if r["relation_type"] == "follower" else "Seguidos")
        retained.append(r["retained"])
        dropped.append(-r["dropped"])
        added.append(r["added"])
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=retained, name="Se mantienen", marker_color=GREEN))
    fig.add_trace(go.Bar(x=labels, y=dropped, name="Se perdieron", marker_color=RED))
    fig.add_trace(go.Bar(x=labels, y=added, name="Nuevas", marker_color=DEFAULT_COLOR))
    fig.update_layout(
        title="Retención entre la primera y la última foto",
        barmode="relative", yaxis_title="Cuentas",
        margin=dict(t=40, b=40), template="plotly_white",
    )
    return fig


# --- Actividad diaria --------------------------------------------------------

def daily_digest(events: List[Dict], posts: List[Dict], comments: List[Dict],
                 mentions: List[Dict], ingest: List[Dict] = None,
                 day: str = None) -> Dict[str, Any]:
    """Resumen de la actividad de un día concreto (fecha UTC YYYY-MM-DD)."""
    day = day or datetime.utcnow().strftime("%Y-%m-%d")

    def on(value) -> bool:
        return (value or "")[:10] == day

    def ev(kind: str) -> List[Dict]:
        return [e for e in (events or [])
                if e.get("event_type") == kind and on(e.get("detected_at"))]

    day_posts = [p for p in (posts or []) if on(p.get("timestamp"))]
    new_fol, lost_fol = ev("new_follower"), ev("lost_follower")
    new_foing, lost_foing = ev("new_following"), ev("lost_following")
    day_comments = [c for c in (comments or []) if on(c.get("timestamp"))]
    day_mentions = [m for m in (mentions or []) if on(m.get("timestamp"))]
    day_ingest = [i for i in (ingest or []) if on(i.get("ts"))]

    likes = sum((p.get("likesCount") or p.get("likes_count") or 0) for p in day_posts)
    return {
        "day": day,
        "posts": len(day_posts),
        "likes": likes,
        "comments_received": len(day_comments),
        "mentions_received": len(day_mentions),
        "new_followers": len(new_fol),
        "lost_followers": len(lost_fol),
        "new_following": len(new_foing),
        "lost_following": len(lost_foing),
        "net_followers": len(new_fol) - len(lost_fol),
        "sources": day_ingest,
        "lost_follower_names": [e.get("username") for e in lost_fol][:25],
        "new_follower_names": [e.get("username") for e in new_fol][:25],
        "commenters": [c.get("owner_username") for c in day_comments][:25],
    }


def activity_series(events: List[Dict], posts: List[Dict], comments: List[Dict],
                    mentions: List[Dict], days: int = 14) -> List[Dict]:
    """Serie diaria de actividad de los últimos N días."""
    from datetime import timedelta

    today = datetime.utcnow().date()
    out = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        g = daily_digest(events, posts, comments, mentions, [], day=d)
        out.append({
            "day": d,
            "posts": g["posts"],
            "comentarios": g["comments_received"],
            "seguidores_neto": g["net_followers"],
            "menciones": g["mentions_received"],
        })
    return out


def fig_activity(series: List[Dict]) -> go.Figure:
    """Gráfico de la actividad diaria."""
    _need_plotly()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=[s["day"] for s in series], y=[s["posts"] for s in series],
                         name="Posts", marker_color=DEFAULT_COLOR))
    fig.add_trace(go.Bar(x=[s["day"] for s in series], y=[s["comentarios"] for s in series],
                         name="Comentarios", marker_color=GREEN))
    fig.add_trace(go.Scatter(x=[s["day"] for s in series],
                             y=[s["seguidores_neto"] for s in series],
                             name="Seguidores (neto)", mode="lines+markers",
                             line=dict(color=AMBER, width=3)))
    fig.update_layout(
        title="Actividad diaria",
        barmode="group", yaxis_title="Cantidad",
        margin=dict(t=40, b=40), template="plotly_white",
    )
    return fig

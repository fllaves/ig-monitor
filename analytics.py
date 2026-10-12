"""Analítica del centro de monitoreo.

Contiene funciones puras (sin dependencias de Streamlit) que transforman los
datos crudos en métricas y figuras de Plotly. `plotly` se importa de forma
opcional para poder ejecutar la lógica pura sin él.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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
    prev_ids = {h["user_id"] for h in rows if h["captured_at"] == prev_date}
    latest_ids = {h["user_id"] for h in rows if h["captured_at"] == latest_date}

    info: Dict[str, Dict] = {}
    for h in rows:
        if h["user_id"] not in info:
            info[h["user_id"]] = h

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
    current_ids = {h["user_id"] for h in rows if h["captured_at"] == latest}

    members: Dict[str, Dict] = {}
    for h in rows:
        if h["user_id"] not in current_ids:
            continue
        m = members.setdefault(h["user_id"], dict(h))
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
    followers = {m["user_id"] for m in relation_members(relation_history, "follower")}
    following = {m["user_id"] for m in relation_members(relation_history, "following")}

    info: Dict[str, Dict] = {}
    for h in relation_history:
        info.setdefault(h["user_id"], h)

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

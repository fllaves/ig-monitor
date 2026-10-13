"""Cliente ligero de la API REST de Apify (sin dependencias externas).

Usa únicamente la librería estándar (`urllib`) para no depender de paquetes
con extensiones nativas. Implementa el flujo completo:

    1. Lanzar un Actor.
    2. Esperar a que termine (polling del estado).
    3. Descargar todos los resultados del dataset (paginado).
"""
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import config

BASE_URL = "https://api.apify.com/v2"

_STATUS_DONE = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


def _url(path: str, token: str, **params: Any) -> str:
    qs = urllib.parse.urlencode({"token": token, **params})
    return f"{BASE_URL}{path}?{qs}"


def _request_json(url: str, data: Dict = None, timeout: int = 60) -> Any:
    headers = {}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_actor(token: str, run_input: Dict[str, Any], actor_id: str = None,
              timeout_secs: int = 900, poll_secs: int = 5) -> Tuple[List[Dict], str]:
    """Ejecuta un Actor y devuelve (items, run_id)."""
    token = token or config.APIFY_TOKEN
    actor_id = actor_id or config.ACTOR_ID
    if not token:
        raise RuntimeError("Falta APIFY_TOKEN. Cópialo en el archivo .env")

    # 1) Lanzar
    run_url = _url(f"/acts/{actor_id}/runs", token)
    payload = _request_json(run_url, data=run_input)
    run = payload["data"]
    run_id = run["id"]
    dataset_id = run.get("defaultDatasetId")

    # 2) Esperar a que termine
    deadline = time.time() + timeout_secs
    status = run.get("status")
    while status not in _STATUS_DONE:
        if time.time() > deadline:
            raise TimeoutError(f"El run {run_id} tardó más de {timeout_secs}s")
        time.sleep(poll_secs)
        info = _request_json(_url(f"/actor-runs/{run_id}", token), timeout=30)
        status = info["data"]["status"]

    if status != "SUCCEEDED":
        raise RuntimeError(f"El run de Apify terminó con estado {status} (run {run_id})")

    items = fetch_dataset(token, dataset_id)
    return items, run_id


def fetch_dataset(token: str, dataset_id: str, page_size: int = 1000) -> List[Dict]:
    """Descarga todos los items de un dataset (paginado)."""
    items: List[Dict] = []
    offset = 0
    while True:
        url = _url(f"/datasets/{dataset_id}/items", token,
                   format="json", offset=offset, limit=page_size, clean=1)
        batch = _request_json(url, timeout=120)
        if not batch:
            break
        items.extend(batch)
        if len(batch) < page_size:
            break
        offset += len(batch)
    return items


class InstagramSource:
    """Fuente de datos de Instagram vía Apify."""

    def __init__(self, token: str = ""):
        self.token = token or config.APIFY_TOKEN

    def fetch_profile(self) -> List[Dict]:
        items, _ = run_actor(
            self.token,
            {
                "resultsType": "details",
                "directUrls": [config.PROFILE_URL],
                "resultsLimit": 1,
            },
        )
        return items

    def fetch_posts(self, limit: int = None) -> List[Dict]:
        items, _ = run_actor(
            self.token,
            {
                "resultsType": "posts",
                "directUrls": [config.PROFILE_URL],
                "resultsLimit": limit or config.RESULTS_LIMIT,
            },
        )
        return items

    def fetch_relations(self, data_to_scrape: str, limit: int = None) -> List[Dict]:
        """Descarga la lista de seguidores ('followers') o seguidos ('following')."""
        limit = limit or (
            config.FOLLOWERS_LIMIT if data_to_scrape == "followers"
            else config.FOLLOWING_LIMIT
        )
        items, _ = run_actor(
            self.token,
            {
                "usernames": [config.USERNAME],
                "dataToScrape": data_to_scrape,
                "resultsLimit": limit,
            },
            actor_id=config.FOLLOWERS_ACTOR_ID,
        )
        # El Actor devuelve filas de error (p. ej. perfil privado) en lugar de lista
        return [i for i in items if not i.get("error")]

    def fetch_followers(self, limit: int = None) -> List[Dict]:
        return self.fetch_relations("followers", limit)

    def fetch_following(self, limit: int = None) -> List[Dict]:
        return self.fetch_relations("following", limit)

    def fetch_comments(self, post_urls: List[str], limit: int = None) -> List[Dict]:
        """Descarga comentarios de una lista de URLs de publicaciones."""
        limit = limit or config.COMMENTS_PER_POST
        items, _ = run_actor(
            self.token,
            {
                "resultsType": "comments",
                "directUrls": post_urls,
                "resultsLimit": limit,
            },
        )
        return [i for i in items if not i.get("error")]

    def fetch_mentions(self, limit: int = None) -> List[Dict]:
        """Descarga publicaciones donde te han etiquetado."""
        limit = limit or config.MENTIONS_LIMIT
        items, _ = run_actor(
            self.token,
            {
                "resultsType": "mentions",
                "directUrls": [config.PROFILE_URL],
                "resultsLimit": limit,
            },
        )
        return [i for i in items if not i.get("error")]

    def fetch_profiles(self, usernames: List[str], timeout_secs: int = 1800) -> List[Dict]:
        """Datos de perfil (bio, categoría…) de una lista de cuentas.

        Se usa para enriquecer y poder categorizar las cuentas seguidas.
        """
        urls = [f"https://www.instagram.com/{str(u).strip().lstrip('@')}/"
                for u in usernames if u]
        if not urls:
            return []
        items, _ = run_actor(
            self.token,
            {"resultsType": "details", "directUrls": urls, "resultsLimit": 1},
            timeout_secs=timeout_secs,
        )
        return [i for i in items if not i.get("error")]

    def fetch_profiles_posts(self, usernames: List[str], limit: int = 20,
                             timeout_secs: int = 1800) -> List[Dict]:
        """Publicaciones recientes de varias cuentas (en una sola corrida)."""
        urls = [f"https://www.instagram.com/{str(u).strip().lstrip('@')}/"
                for u in usernames if u]
        if not urls:
            return []
        items, _ = run_actor(
            self.token,
            {"resultsType": "posts", "directUrls": urls, "resultsLimit": limit},
            timeout_secs=timeout_secs,
        )
        return [i for i in items if not i.get("error")]


def _iso(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


class ThreadsSource:
    """Perfiles públicos de Threads (Meta) y sus publicaciones recientes.

    Usa el Actor oficial `apify/threads-profile-api-scraper`. No necesita login
    ni cookies: solo datos públicos. Es la única red además de Instagram donde
    el proyecto puede mirar sin tocar la cuenta propia.
    """

    def __init__(self, token: str = None):
        self.token = token or config.APIFY_TOKEN

    def fetch_profiles(self, usernames: List[str], timeout_secs: int = 600) -> List[Dict]:
        names = [str(u).strip().lstrip("@") for u in (usernames or []) if u]
        if not names:
            return []
        items, _ = run_actor(self.token, {"usernames": names},
                             actor_id=config.THREADS_ACTOR_ID,
                             timeout_secs=timeout_secs)
        return [i for i in items if i.get("username")]

    def fetch_posts(self, usernames: List[str], timeout_secs: int = 600) -> List[Dict]:
        """Aplana los `latestPosts` de cada perfil en filas listas para guardar."""
        out: List[Dict] = []
        for prof in self.fetch_profiles(usernames, timeout_secs=timeout_secs):
            uname = prof.get("username")
            is_private = prof.get("is_private") or prof.get("text_post_app_is_private")
            for p in prof.get("latestPosts") or []:
                cap = p.get("caption")
                if isinstance(cap, dict):
                    cap = cap.get("text") or ""
                code = p.get("code") or ""
                out.append({
                    "post_id": str(p.get("pk") or p.get("id") or code),
                    "username": uname,
                    "code": code,
                    "url": p.get("canonical_url") or (
                        f"https://www.threads.net/@{uname}/post/{code}" if code else ""),
                    "text": cap or "",
                    "like_count": p.get("like_count") or 0,
                    "taken_at": _iso(p.get("taken_at")),
                    "media_type": p.get("media_type"),
                    "tags": [((t.get("user") or {}).get("username") or "")
                             for t in ((p.get("usertags") or {}).get("in") or [])],
                    "is_private": bool(is_private),
                    "followers": prof.get("follower_count") or 0,
                    "bio": prof.get("biography") or "",
                })
        return out

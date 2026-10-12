"""Clasificador de cuentas por categoría.

Clasifica una cuenta a partir de la información pública disponible:
username, nombre y biografía (esta última solo si se ha enriquecido con Apify).
Es una heurística por palabras clave: rápida, gratis y sin dependencias.
"""
import re
from typing import Iterable, Optional

# Orden: las categorías más específicas primero ayuda cuando hay empate.
CATEGORIES = {
    "Comics/Ilustración": [
        "comic", "comics", "cartoon", "manga", "anime", "ilustra", "illustrat",
        "drawing", "draw", "sketch", "ink", "webtoon", "viñeta", "graphic novel",
    ],
    "Gaming": [
        "game", "gamer", "gaming", "twitch", "esport", "e-sport", "playstation",
        "xbox", "nintendo", "steam", "speedrun",
    ],
    "Música/Audio": [
        "music", "musica", "música", "dj", "beat", "beats", "sound", "audio",
        "rap", "rock", "jazz", "song", "producer", "label", "records", "banda",
        "concierto", "live", "synth", "drum",
    ],
    "Cine/TV/Series": [
        "film", "movie", "cine", "cinema", "series", "actor", "actress",
        "director", "netflix", "pelicula", "película",
    ],
    "Tecnología/Programación": [
        "dev", "code", "coder", "coding", "tech", "software", "data", "python",
        "javascript", "js", "web", "cloud", "hacker", "devops", "program",
        "ingenier", "engineer", "ai", "machinelearning", "robot", "startup",
    ],
    "Emprendimiento/Negocios": [
        "founder", "ceo", "cto", "vc", "venture", "business", "negocio",
        "emprende", "emprendimiento", "capital", "invest", "market", "ventas",
        "consultor", "coach", "finanz", "financ", "crypto", "money",
    ],
    "Deporte/Fitness": [
        "fit", "fitness", "gym", "run", "runner", "running", "sport", "deporte",
        "futbol", "fútbol", "soccer", "bike", "cycling", "crossfit", "train",
        "natacion", "swim", "surf", "climb", "escalada", "yoga", "pilates",
        "bodybuilding", "atleta", "athlete",
    ],
    "Comida/Cocina": [
        "food", "cook", "chef", "cocina", "resto", "restaurant", "cafe",
        "coffee", "bakery", "pizza", "recipe", "kitchen", "bar", "comida",
        "gastronom", "sushi", "burger", "vegan",
    ],
    "Viajes": [
        "travel", "trip", "viaj", "wander", "nomad", "tour", "adventure",
        "explor", "hotel", "destino", "turismo",
    ],
    "Moda/Belleza": [
        "fashion", "style", "moda", "beauty", "makeup", "hair", "dress",
        "wear", "skincare", "belleza", "estilista", "stylist", "boutique",
    ],
    "Arte/Diseño": [
        "art", "arte", "artist", "design", "diseño", "graphic", "paint",
        "photo", "foto", "fotograf", "studio", "creative", "creativ",
        "arquitect", "architect", "mural", "escultor",
    ],
    "Educación": [
        "edu", "learn", "academy", "school", "escuela", "curso", "teacher",
        "profesor", "prof", "clase", "universidad", "university", "bootcamp",
        "tutorial", "aprender",
    ],
    "Ciencia/Salud": [
        "sci", "science", "ciencia", "med", "doctor", "health", "salud",
        "astro", "physics", "neuro", "biolog", "quimic", "psicolog",
        "psycholog", "nutri", "terapia",
    ],
    "Noticias/Media": [
        "news", "noticias", "times", "media", "journal", "report", "magazine",
        "press", "prensa", "diario", "periodis",
    ],
    "Humor/Entretenimiento": [
        "humor", "meme", "memes", "joke", "comedy", "comedia", "funny",
        "chiste", "standup", "stand-up", "entretenimiento", "show",
    ],
    "Familia/Lifestyle": [
        "family", "familia", "mom", "mama", "mamá", "dad", "papa", "papá",
        "home", "casa", "lifestyle", "daily", "life", "personal",
    ],
    "Mascotas/Animales": [
        "pet", "pets", "dog", "dogs", "perro", "cat", "cats", "gato", "animal",
        "vet", "rescate", "rescue",
    ],
}

CATEGORY_LIST = list(CATEGORIES.keys()) + ["Otros"]


def _normalize(texts: Iterable[Optional[str]]) -> str:
    joined = " ".join(t for t in texts if t)
    joined = joined.lower()
    # separar por . _ - y espacios para que "dj.miss" y "dj_miss" coincidan
    joined = re.sub(r"[._\-/|,]+", " ", joined)
    return joined


def category_for(username: Optional[str] = None, full_name: Optional[str] = None,
                 bio: Optional[str] = None) -> str:
    """Devuelve la categoría más probable según palabras clave."""
    hay = _normalize([username, full_name, bio])
    if not hay.strip():
        return "Otros"

    scores = {}
    for cat, keywords in CATEGORIES.items():
        hits = sum(1 for kw in keywords if kw in hay)
        if hits:
            scores[cat] = hits
    if not scores:
        return "Otros"
    # empate -> orden de definición (las más específicas van primero)
    best = max(scores.values())
    for cat in CATEGORIES:
        if scores.get(cat) == best:
            return cat
    return "Otros"

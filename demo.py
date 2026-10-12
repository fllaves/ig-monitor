"""Genera datos de demostración realistas para previsualizar el dashboard
sin necesidad de token de Apify. Se guardan directamente en la base local.
"""
import random
from datetime import datetime, timedelta, timezone

import analytics
import config
import storage

random.seed(42)

_CAPTIONS = [
    "Nueva sesión de fotos en la ciudad 🏙️✨ #photography #city #portrait",
    "Detrás de cámaras del último proyecto 🎬 #behindthescenes #creator",
    "Atardecer que no necesita filtros 🌅 #sunset #nature #goldenhour",
    "Mi rutina de edición en 3 pasos 🎨 #editing #tutorial #reels",
    "Colaboración con @amigo_creador 🤝 #collab #creadores #latino",
    "Tips rápidos para mejorar tu feed 📱 #tips #instagram #crecimiento",
    "Este lugar es otro nivel 📍 #travel #explore #wanderlust",
    "Resumen del mes: gracias por tanto apoyo ❤️ #gracias #comunidad",
    "Probadita del nuevo contenido que viene 🔥 #sneakpeek #pronto",
    "Pregunta del día: ¿qué tema quieren que cubra? 👇 #comunidad #pregunta",
    "El poder de un buen ángulo 📐 #fotografia #angulo #detalle",
    "Domingo de reflexión y café ☕ #domingo #mindset #motivacion",
    "Lanzamiento de mi proyecto personal 🚀 #lanzamiento #emprendimiento",
    "Antes y después de la edición 🖼️ #beforeafter #edicion",
    "Un reel que me costó 4 horas grabar 😅 #reel #proceso #esfuerzo",
]

_HASHTAGS = [
    "photography", "reels", "creator", "latino", "instagram", "viral",
    "motivacion", "travel", "city", "editing", "tips", "comunidad",
    "emprendimiento", "lifestyle", "behindthescenes",
]

_CONTENT_TYPES = ["Foto", "Reel", "Foto", "Carrusel", "Reel", "Foto"]

_NAMES = [
    ("maria.lopez", "María López"), ("carlos.r", "Carlos Ramírez"),
    ("sofia.gomez", "Sofía Gómez"), ("andres.m", "Andrés Martínez"),
    ("vale.hernandez", "Valentina Hernández"), ("diego_t", "Diego Torres"),
    ("lau.fernandez", "Laura Fernández"), ("jorge.p", "Jorge Pérez"),
    ("camila.s", "Camila Sánchez"), ("pedro.r", "Pedro Rodríguez"),
    ("ana.maria", "Ana María Díaz"), ("luis.g", "Luis García"),
    ("isabel.v", "Isabel Vargas"), ("miguel.a", "Miguel Ángel"),
    ("caro.r", "Carolina Ruiz"), ("felipe.o", "Felipe Ortega"),
    ("dana.c", "Daniela Castro"), ("oscar.m", "Óscar Molina"),
    ("paula.n", "Paula Navarro"), ("raul.s", "Raúl Salazar"),
    ("gabriela.f", "Gabriela Fuentes"), ("ivan.l", "Iván Lara"),
    ("nadia.r", "Nadia Romero"), ("sergio.v", "Sergio Vidal"),
    ("elena.p", "Elena Peña"), ("tomas.g", "Tomás Guerrero"),
    ("julia.m", "Julia Mendoza"), ("hugo.c", "Hugo Cabrera"),
]


def _build_post(seed: int, days_ago: int, hour: int):
    rnd = random.Random(seed)
    caption = _CAPTIONS[seed % len(_CAPTIONS)]
    tags = rnd.sample(_HASHTAGS, k=rnd.randint(2, 5))
    ctype = _CONTENT_TYPES[seed % len(_CONTENT_TYPES)]

    now = datetime.now(timezone.utc)
    published = now - timedelta(days=days_ago, hours=rnd.randint(0, 6))
    published = published.replace(hour=hour, minute=rnd.randint(0, 59), second=0)

    likes = rnd.randint(40, 420)
    if seed % 9 == 0:  # algún post "viral"
        likes = int(likes * rnd.uniform(2.5, 4.5))
    comments = int(likes * rnd.uniform(0.03, 0.10))
    views = int(likes * rnd.uniform(8, 25)) if ctype == "Reel" else None

    type_map = {"Foto": "Image", "Carrusel": "Sidecar", "Reel": "Video"}
    product_map = {"Foto": "feed", "Carrusel": "feed", "Reel": "clips"}

    return {
        "id": f"demo_{seed}_{days_ago}_{hour}",
        "shortCode": f"DEMO{seed:04d}",
        "url": f"https://www.instagram.com/p/DEMO{seed:04d}/",
        "caption": caption,
        "hashtags": tags,
        "mentions": ["amigo_creador"] if seed % 4 == 0 else [],
        "type": type_map[ctype],
        "productType": product_map[ctype],
        "likesCount": likes,
        "commentsCount": comments,
        "videoPlayCount": views,
        "videoViewCount": views,
        "timestamp": published.isoformat(),
        "displayUrl": "",
        "isPinned": seed == 0,
        "ownerUsername": config.USERNAME,
        "ownerFullName": "IG FV",
    }


def _account(i: int) -> dict:
    username, full_name = _NAMES[i % len(_NAMES)]
    return {
        "sourceUsername": config.USERNAME,
        "userId": f"demo_uid_{i}",
        "username": username,
        "fullName": full_name,
        "profilePicUrl": "",
        "isVerified": False,
        "isPrivate": i % 5 == 0,
        "type": "follower",
    }


def seed_demo(clear: bool = True) -> None:
    if clear:
        storage.reset_db()
    else:
        storage.init_db()

    now = datetime.now(timezone.utc)

    # --- Publicaciones (últimos ~120 días) ---
    posts = []
    for i in range(46):
        days_ago = int(i * 2.6)
        hour = random.Random(i).randint(8, 22)
        posts.append(_build_post(i, days_ago, hour))

    # --- Historial de perfil (crecimiento semanal ~2 meses) ---
    start_followers = 1180
    end_followers = 1854
    weeks = 9
    for w in range(weeks):
        when = now - timedelta(weeks=(weeks - 1 - w))
        frac = w / (weeks - 1)
        followers = int(start_followers + (end_followers - start_followers) * frac)
        followers += random.Random(w).randint(-15, 25)
        following = int(540 + w * 4)
        snapshot = {
            "username": config.USERNAME,
            "fullName": "IG FV",
            "biography": "Cuenta de demostración",
            "followersCount": followers,
            "followsCount": following,
            "postsCount": max(1, round(len(posts) * (w + 1) / weeks)),
            "verified": False,
            "isBusinessAccount": True,
            "businessCategoryName": "Digital creator",
            "profilePicUrl": "",
            "externalUrl": "",
        }
        storage.save_profile_snapshot(snapshot, when.isoformat())

    captured_at = now.isoformat()
    storage.upsert_posts(posts, captured_at)

    # Historial de engagement para las 5 publicaciones top
    top = sorted(posts, key=lambda p: p["likesCount"], reverse=True)[:5]
    conn = storage._connect()
    for p in top:
        likes_now = p["likesCount"]
        for step, days_ago in enumerate([14, 7, 0]):
            when = now - timedelta(days=days_ago)
            conn.execute(
                "INSERT INTO post_history(post_id, captured_at, likes_count, comments_count, view_count)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    p["id"],
                    when.isoformat(),
                    int(likes_now * (0.3 + 0.5 * step / 2)),
                    int(p["commentsCount"] * (0.3 + 0.5 * step / 2)),
                    p.get("videoPlayCount"),
                ),
            )
    conn.commit()
    conn.close()

    # --- Seguidores y seguidos (dos snapshots para mostrar cambios) ---
    followers_old = [_account(i) for i in range(25)]
    followers_new = [_account(i) for i in range(25)]
    # 3 altas nuevas y 2 bajas
    followers_new += [_account(25), _account(26), _account(27)]
    followers_new = [f for f in followers_new if f["userId"] not in ("demo_uid_3", "demo_uid_11")]

    following_old = [_account(i) for i in range(18)]
    following_new = [f for f in following_old if f["userId"] != "demo_uid_7"]  # dejó de seguir 1

    seven_days_ago = (now - timedelta(days=7)).isoformat()
    storage.save_relations(followers_old, "follower", seven_days_ago)
    storage.save_relations(following_old, "following", seven_days_ago)
    storage.save_relations(followers_new, "follower", captured_at)
    storage.save_relations(following_new, "following", captured_at)

    # Eventos de cambio (historial persistente)
    storage.save_relation_events(analytics.build_relation_events(storage.get_relation_history()))

    # Comentarios de demostración
    demo_comments = [
        {"id": "dc1", "postUrl": posts[0]["url"], "text": "¡Gracias por tanto valor! 🙌",
         "ownerUsername": "fan_uno", "owner": {"id": "u1"}, "likesCount": 12, "timestamp": captured_at},
        {"id": "dc2", "postUrl": posts[0]["url"], "text": "Me encanta cómo explicas 🔥",
         "ownerUsername": "seguidor_dos", "owner": {"id": "u2"}, "likesCount": 8, "timestamp": captured_at},
        {"id": "dc3", "postUrl": posts[1]["url"], "text": "No me gustó nada este video 👎",
         "ownerUsername": "critico_uno", "owner": {"id": "u3"}, "likesCount": 1, "timestamp": captured_at},
        {"id": "dc4", "postUrl": posts[1]["url"], "text": "Muy claro, como siempre.",
         "ownerUsername": "seguidor_dos", "owner": {"id": "u2"}, "likesCount": 5, "timestamp": captured_at},
        {"id": "dc5", "postUrl": posts[2]["url"], "text": "Crack total 💪",
         "ownerUsername": "fan_uno", "owner": {"id": "u1"}, "likesCount": 9, "timestamp": captured_at},
    ]
    storage.save_comments(demo_comments, captured_at)

    # Menciones de demostración
    demo_mentions = [
        {"id": "dm1", "shortCode": "MENTION1", "url": "https://www.instagram.com/p/MENTION1/",
         "caption": "Gran charla en el evento", "ownerUsername": "asistente_conf",
         "timestamp": captured_at, "likesCount": 120},
        {"id": "dm2", "shortCode": "MENTION2", "url": "https://www.instagram.com/p/MENTION2/",
         "caption": "Aplicando lo aprendido, gracias", "ownerUsername": "alumno_platzi",
         "timestamp": captured_at, "likesCount": 85},
    ]
    storage.save_mentions(demo_mentions, captured_at)

    storage.save_run(
        now.isoformat(), "demo", "demo", len(posts), source="demo",
        followers_count=len(followers_new), following_count=len(following_new),
    )


if __name__ == "__main__":
    seed_demo()
    print(f"Datos de demostración creados en {config.DB_PATH}")

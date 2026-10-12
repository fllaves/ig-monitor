"""Centro de monitoreo de Instagram — Dashboard interactivo con Streamlit.

Ejecutar con:
    streamlit run app.py
"""
from typing import Any, Dict, List, Optional

import streamlit as st

import analytics
import config
import storage
from sync import do_sync

st.set_page_config(
    page_title=f"Centro de monitoreo · {config.DISPLAY_NAME}",
    page_icon="📊",
    layout="wide",
)


# --- Carga de datos ----------------------------------------------------------

def load_all() -> Dict[str, Any]:
    storage.init_db()
    history = storage.get_profile_history()
    latest = history[-1] if history else None
    prev = history[-2] if len(history) >= 2 else None
    followers = (latest or {}).get("followers_count") or 0
    posts_raw = storage.get_posts()
    posts = analytics.enrich_posts(posts_raw, followers)
    return {
        "history": history,
        "latest": latest,
        "prev": prev,
        "posts": posts,
        "runs": storage.get_runs(),
        "relation_history": storage.get_relation_history(),
        "comments": storage.get_comments(),
        "mentions": storage.get_mentions(),
        "events": storage.get_relation_events(),
    }


def _change_table(accounts: List[Dict], cols: List[str]) -> None:
    if not accounts:
        st.caption("Sin cambios.")
        return
    rows = [{
        "Usuario": a.get("username"),
        "Nombre": a.get("full_name") or "",
        "Verificado": "✅" if a.get("is_verified") else "",
        "Privado": "🔒" if a.get("is_private") else "",
    } for a in accounts]
    st.dataframe(rows, width="stretch", hide_index=True)


def _render_relation_tab(relation_type: str, delta: Optional[Dict],
                         members: List[Dict]) -> None:
    if relation_type == "follower":
        new_label, lost_label, title = "Nuevos seguidores", "Te dejaron de seguir", "Seguidores"
    else:
        new_label, lost_label, title = "Nuevos seguidos", "Dejaste de seguir", "Seguidos"

    st.markdown(f"#### {title} ({len(members)})")

    if delta is None:
        st.caption("Necesitas al menos dos sincronizaciones para detectar cambios.")
    else:
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.markdown(f"**{new_label}** ({len(delta['new'])})")
            _change_table(delta["new"], ["Usuario", "Nombre"])
        with c2:
            st.markdown(f"**{lost_label}** ({len(delta['lost'])})")
            _change_table(delta["lost"], ["Usuario", "Nombre"])

    st.markdown("**Lista completa con historial**")
    rows = [{
        "Usuario": m.get("username"),
        "Nombre": m.get("full_name") or "",
        "Verificado": "✅" if m.get("is_verified") else "",
        "Privado": "🔒" if m.get("is_private") else "",
        "Visto desde": (m.get("first_seen") or "")[:10],
        "Visto hasta": (m.get("last_seen") or "")[:10],
    } for m in members]
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.caption("Sin datos todavía.")


# --- Sidebar ----------------------------------------------------------------

with st.sidebar:
    st.title("📊 Centro de monitoreo")
    st.caption(f"Cuenta: **{config.DISPLAY_NAME}**")

    if config.APIFY_TOKEN:
        st.success("Apify: token configurado")
    else:
        st.warning("Apify: sin token (copia el token en `.env`)")

    st.divider()

    posts_limit = st.number_input(
        "Publicaciones por sincronización", min_value=10, max_value=1000,
        value=config.RESULTS_LIMIT, step=10,
    )
    with st.expander("Límites de seguidores/seguidos"):
        followers_limit = st.number_input(
            "Seguidores por sincronización", min_value=10, max_value=5000,
            value=config.FOLLOWERS_LIMIT, step=10,
        )
        following_limit = st.number_input(
            "Seguidos por sincronización", min_value=10, max_value=5000,
            value=config.FOLLOWING_LIMIT, step=10,
        )

    if st.button("🔄 Sincronizar con Apify", width="stretch"):
        if not config.APIFY_TOKEN:
            st.error("Falta APIFY_TOKEN. Crea el archivo `.env` (ver `.env.example`).")
        else:
            with st.spinner("Descargando datos de Instagram vía Apify… (puede tardar un par de minutos)"):
                try:
                    result = do_sync(
                        token=config.APIFY_TOKEN, limit=int(posts_limit),
                        followers_limit=int(followers_limit),
                        following_limit=int(following_limit),
                    )
                    st.success(
                        f"{result['message']} · {result['posts']} posts · "
                        f"{result['followers']} seguidores · {result['following']} seguidos · "
                        f"{result.get('comments', 0)} comentarios · {result.get('mentions', 0)} menciones"
                    )
                    for err in result["errors"]:
                        st.warning(err)
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Error: {exc}")

    if st.button("🎲 Cargar datos demo", width="stretch"):
        if storage.has_data():
            st.warning("Ya hay datos. Usa “Reiniciar datos” si quieres empezar con la demo.")
        else:
            import demo
            demo.seed_demo()
            st.rerun()

    if st.button("🗑️ Reiniciar datos", width="stretch"):
        storage.reset_db()
        st.rerun()

    st.divider()
    st.caption("Datos acumulados localmente en `data/instagram_monitor.db`.")


# --- Cuerpo ----------------------------------------------------------------

data = load_all()
latest: Dict = data["latest"] or {}
posts: List[Dict] = data["posts"]

if not latest and not posts:
    st.title(f"Monitoreo de {config.DISPLAY_NAME}")
    st.info(
        "Todavía no hay datos. Tienes dos opciones:\n\n"
        "1. **Cargar datos demo** desde la barra lateral para ver el dashboard al instante.\n"
        "2. **Sincronizar con Apify**: tu token ya está en `.env`; pulsa “Sincronizar con Apify”."
    )
    st.stop()

# --- Cabecera del perfil ----------------------------------------------------

if latest:
    # Cabecera neutra: NO mostramos username, nombre real, bio, enlace ni foto,
    # para no revelar la cuenta si el panel se comparte.
    left, right = st.columns([1, 3], gap="large")
    with left:
        st.markdown("### 📊")
    with right:
        st.title(config.DISPLAY_NAME)
        st.caption("Panel privado de monitoreo · datos obtenidos con Apify")

# --- KPIs --------------------------------------------------------------------

has_real_sync = any(r.get("source") == "apify" for r in data["runs"])
if not has_real_sync:
    st.warning(
        "📌 Estás viendo **datos de demostración**. Pulsa “Sincronizar con Apify” "
        "para cargar tus datos reales."
    )

kpis = analytics.compute_kpis(posts, data["latest"], data["prev"])

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Seguidores", f"{kpis['followers']:,}",
          delta=f"{kpis['followers_delta']:+d}" if kpis["followers_delta"] is not None else None)
c2.metric("Siguiendo", f"{kpis['following'] or 0:,}")
c3.metric("Publicaciones", f"{kpis['posts']:,}")
c4.metric("Likes promedio", f"{kpis['avg_likes']:,.1f}")
c5.metric("Comentarios prom.", f"{kpis['avg_comments']:,.1f}")
c6.metric("Engagement rate", f"{kpis['avg_engagement_rate']:.2f}%")

st.divider()

# --- Gráficos ----------------------------------------------------------------

followers_series = analytics.follower_series(data["history"])

row1_a, row1_b = st.columns([3, 2], gap="large")
with row1_a:
    if followers_series:
        st.plotly_chart(analytics.fig_followers(followers_series), width="stretch")
    else:
        st.info("Historial de seguidores disponible tras varias sincronizaciones.")
with row1_b:
    ctd = analytics.content_type_distribution(posts)
    if ctd:
        st.plotly_chart(analytics.fig_content_type(ctd), width="stretch")

row2_a, row2_b = st.columns(2, gap="large")
with row2_a:
    pot = analytics.posts_over_time(posts, bucket="month")
    if pot:
        st.plotly_chart(analytics.fig_posts_over_time(pot), width="stretch")
with row2_b:
    hd = analytics.hour_distribution(posts)
    if hd:
        st.plotly_chart(analytics.fig_hour_distribution(hd), width="stretch")

row3_a, row3_b = st.columns(2, gap="large")
with row3_a:
    top = analytics.top_posts(posts, n=10, metric="likes")
    if top:
        st.plotly_chart(analytics.fig_top_posts(top, metric="likes"), width="stretch")
with row3_b:
    hf = analytics.hashtag_frequency(posts, top_n=15)
    if hf:
        st.plotly_chart(analytics.fig_hashtags(hf), width="stretch")

st.plotly_chart(analytics.fig_engagement_scatter(posts), width="stretch")

st.divider()

# --- Seguidores y seguidos -----------------------------------------------------

st.subheader("👥 Seguidores y seguidos (con historial)")

relation_history: List[Dict] = data["relation_history"]
followers_members = analytics.relation_members(relation_history, "follower")
following_members = analytics.relation_members(relation_history, "following")
d_followers = analytics.relation_delta(relation_history, "follower")
d_following = analytics.relation_delta(relation_history, "following")
rel_series = analytics.relation_counts_series(relation_history)

if not followers_members and not following_members:
    st.info("Aún no hay listas de seguidores/seguidos. Sincroniza con Apify o carga datos demo.")
else:
    st.caption(
        "ℹ️ El plan gratuito de Apify devuelve solo la **primera página** de cada lista "
        "(~20 cuentas, las más recientes). Para la lista completa de seguidores necesitas un plan de pago."
    )

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Seguidores (lista)", len(followers_members),
              delta=(f"{d_followers['net']:+d}" if d_followers else None))
    k2.metric("Seguidos (lista)", len(following_members),
              delta=(f"{d_following['net']:+d}" if d_following else None))
    k3.metric("Nuevos seguidores", len(d_followers["new"]) if d_followers else 0)
    k4.metric("Te dejaron de seguir", len(d_followers["lost"]) if d_followers else 0)
    k5.metric("Nuevos seguidos", len(d_following["new"]) if d_following else 0)
    k6.metric("Dejaste de seguir", len(d_following["lost"]) if d_following else 0)

    if rel_series and len(rel_series) >= 1:
        st.plotly_chart(analytics.fig_relation_counts(rel_series), width="stretch")

    deltas = [d for d in (d_followers, d_following) if d]
    if deltas:
        st.plotly_chart(analytics.fig_relation_flow(deltas), width="stretch")

    tab_f, tab_g = st.tabs(["Seguidores", "Seguidos"])
    with tab_f:
        _render_relation_tab("follower", d_followers, followers_members)
    with tab_g:
        _render_relation_tab("following", d_following, following_members)

st.divider()

# --- Historial de cambios -----------------------------------------------------

st.subheader("🕓 Historial de cambios (quién y cuándo)")
events = data["events"]
if events:
    event_labels = {
        "new_follower": "🟢 Nuevo seguidor",
        "lost_follower": "🔻 Te dejó de seguir",
        "new_following": "🟢 Nuevo seguido",
        "lost_following": "🔻 Dejaste de seguir",
    }
    ev_rows = [{
        "Fecha": (e.get("detected_at") or "")[:19].replace("T", " "),
        "Evento": event_labels.get(e.get("event_type"), e.get("event_type")),
        "Usuario": e.get("username"),
        "Nombre": e.get("full_name") or "",
    } for e in events]
    st.dataframe(ev_rows, width="stretch", hide_index=True)
else:
    st.caption("Aún no hay cambios registrados. Aparecerán a partir de tu segunda sincronización.")

st.divider()

# --- Mutuales ----------------------------------------------------------------

st.subheader("🔁 Seguidores mutuos")
mutuals = analytics.compute_mutuals(data["relation_history"])
m1, m2, m3 = st.columns(3)
m1.metric("Mutuales", len(mutuals["mutuals"]))
m2.metric("Sigues y no te siguen", len(mutuals["not_followed_back"]))
m3.metric("Te siguen y no les sigues", len(mutuals["not_following_back"]))


def _accounts_table(accounts):
    rows = [{"Usuario": a.get("username"), "Nombre": a.get("full_name") or "",
             "Verificado": "✅" if a.get("is_verified") else "",
             "Privado": "🔒" if a.get("is_private") else ""} for a in accounts]
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.caption("Sin datos.")


with st.expander("Ver listas de mutuales y no recíprocos"):
    t1, t2, t3 = st.tabs(["Mutuales", "No te siguen de vuelta", "No les sigues"])
    with t1:
        _accounts_table(mutuals["mutuals"])
    with t2:
        _accounts_table(mutuals["not_followed_back"])
    with t3:
        _accounts_table(mutuals["not_following_back"])

st.divider()

# --- Calidad de audiencia ----------------------------------------------------

st.subheader("🎯 Calidad de audiencia")
quality = analytics.audience_quality(followers_members)
q1, q2, q3, q4 = st.columns(4)
q1.metric("Cuentas analizadas", quality["total"])
q2.metric("Verificadas", quality["verified"])
q3.metric("Privadas", quality["private"])
q4.metric("Sospechosas", quality["suspicious"])
st.caption("Heurística simple sobre la muestra de seguidores (el plan gratis limita la lista a ~50).")

st.divider()

# --- Comentarios -------------------------------------------------------------

st.subheader("💬 Comentarios")
comments = data["comments"]
if comments:
    cstats = analytics.comment_stats(comments)
    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.metric("Comentarios", cstats["total"])
    cc2.metric("Positivos", cstats["positive"])
    cc3.metric("Neutrales", cstats["neutral"])
    cc4.metric("Negativos", cstats["negative"])
    col_sent, col_top = st.columns([1, 2], gap="large")
    with col_sent:
        st.plotly_chart(analytics.fig_sentiment(cstats), width="stretch")
    with col_top:
        st.markdown("**Fans más activos**")
        if cstats["top_commenters"]:
            st.dataframe([{"Usuario": t["username"], "Comentarios": t["count"]}
                          for t in cstats["top_commenters"]], width="stretch", hide_index=True)
    with st.expander("Ver todos los comentarios"):
        st.dataframe([{
            "Fecha": (c.get("timestamp") or "")[:19].replace("T", " "),
            "Post": c.get("post_id") or "",
            "Usuario": c.get("owner_username"),
            "Comentario": config.mask((c.get("text") or "")[:120]),
            "Sentimiento": analytics.sentiment(c.get("text")),
            "Likes": c.get("likes_count"),
        } for c in comments], width="stretch", hide_index=True)
else:
    st.caption("Aún no hay comentarios. Se descargarán en la próxima sincronización.")

st.divider()

# --- Menciones ---------------------------------------------------------------

st.subheader("🏷️ Menciones (quién te etiqueta)")
mentions = data["mentions"]
if mentions:
    st.dataframe([{
        "Fecha": (m.get("timestamp") or "")[:19].replace("T", " "),
        "Quién": m.get("owner_username"),
        "Caption": config.mask((m.get("caption") or "")[:120]),
        "Likes": m.get("likes_count"),
        "URL": m.get("url") or "",
    } for m in mentions], width="stretch", hide_index=True)
else:
    st.caption("Aún no hay menciones. Se descargarán en la próxima sincronización.")

st.divider()

# --- Informe Excel -----------------------------------------------------------

st.subheader("📄 Informe")
try:
    import report
    st.download_button(
        "⬇️ Descargar informe Excel (.xlsx)",
        data=report.build_report_bytes(),
        file_name=f"informe_{config.DISPLAY_NAME.replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
except Exception as exc:  # noqa: BLE001
    st.caption(f"No se pudo generar el informe (¿falta openpyxl?): {exc}")

st.divider()

# --- Tabla de publicaciones ---------------------------------------------------

st.subheader("Publicaciones")

filter_type = st.selectbox(
    "Filtrar por tipo de contenido",
    ["Todos"] + [d["type"] for d in analytics.content_type_distribution(posts)],
)

rows = []
for p in posts:
    if filter_type != "Todos" and p.get("content_type") != filter_type:
        continue
    cap = config.mask((p.get("caption") or "").replace("\n", " ").strip())
    rows.append({
        "Fecha": (p.get("dt").strftime("%Y-%m-%d %H:%M") if p.get("dt") else "—"),
        "Tipo": p.get("content_type"),
        "Caption": cap[:80] + ("…" if len(cap) > 80 else ""),
        "Likes": p.get("likesCount"),
        "Comentarios": p.get("commentsCount"),
        "Vistas": p.get("videoPlayCount") or p.get("videoViewCount") or 0,
        "ER %": p.get("engagement_rate"),
        "URL": p.get("url") or "",
    })

if rows:
    st.dataframe(rows, width="stretch", hide_index=True)

    import csv
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    st.download_button(
        "⬇️ Descargar CSV",
        data=buf.getvalue(),
        file_name=f"{config.DISPLAY_NAME.replace(' ', '_')}_publicaciones.csv",
        mime="text/csv",
    )
else:
    st.info("No hay publicaciones que coincidan con el filtro.")

# --- JSON crudo de una publicación -------------------------------------------

with st.expander("🔍 Ver JSON crudo completo de una publicación (sin perder datos)"):
    shortcodes = [p.get("shortCode") or p.get("id") for p in posts if p.get("shortCode") or p.get("id")]
    if shortcodes:
        chosen = st.selectbox("Publicación", shortcodes)
        raw = storage.get_post_raw(chosen)
        if raw:
            # Enmascarar cualquier aparición del username real dentro del JSON
            import json as _json
            raw = _json.loads(config.mask(_json.dumps(raw, ensure_ascii=False)))
            st.json(raw)
        else:
            st.caption("No hay JSON crudo para esta publicación.")
    else:
        st.caption("Sin publicaciones.")

# --- Historial de ejecuciones --------------------------------------------------

with st.expander("Historial de sincronizaciones"):
    if data["runs"]:
        st.dataframe(data["runs"], width="stretch", hide_index=True)
    else:
        st.caption("Aún no hay ejecuciones registradas.")

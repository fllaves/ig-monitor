"""Centro de monitoreo de Instagram — Dashboard interactivo con Streamlit.

Ejecutar con:
    streamlit run app.py
"""
import json
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
    if not storage.get_watchlist():
        storage.add_watch_accounts(config.WATCHLIST)
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
        "profiles": storage.get_account_profiles(),
        "external_posts": storage.get_external_posts(),
        "external_comments": storage.get_external_comments(),
        "story_mentions": storage.get_story_mentions(),
        "ingest": storage.get_ingest_log(),
        "threads": storage.get_threads_posts(),
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

    if not config.USERNAME:
        st.error("Falta `IG_USERNAME` en los secretos (o `.env`).")

    # Mensaje de la última acción (sobrevive al rerun)
    last_flash = st.session_state.pop("flash", None)
    if last_flash:
        if last_flash.get("ok"):
            st.success(last_flash["message"])
        else:
            st.error(last_flash["message"])
        for err_line in last_flash.get("errors", []):
            st.warning(f"⚠ {err_line}")

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
            st.session_state["flash"] = {
                "ok": False, "message": "Falta APIFY_TOKEN en los secretos.", "errors": []}
        elif not config.USERNAME:
            st.session_state["flash"] = {
                "ok": False,
                "message": "Falta IG_USERNAME en los secretos (o en `.env`).",
                "errors": []}
        else:
            with st.spinner("Descargando datos vía Apify… (puede tardar varios minutos)"):
                try:
                    result = do_sync(
                        token=config.APIFY_TOKEN, limit=int(posts_limit),
                        followers_limit=int(followers_limit),
                        following_limit=int(following_limit),
                    )
                    st.session_state["flash"] = {
                        "ok": True,
                        "message": (
                            f"{result['message']} · {result['posts']} posts · "
                            f"{result['followers']} seguidores · {result['following']} seguidos · "
                            f"{result.get('comments', 0)} comentarios · {result.get('mentions', 0)} menciones"
                        ),
                        "errors": list(result.get("errors", [])),
                    }
                except Exception as exc:  # noqa: BLE001
                    st.session_state["flash"] = {
                        "ok": False, "message": f"Error: {exc}", "errors": []}
        st.rerun()

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

    with st.expander("🔧 Diagnóstico de conexión"):
        if st.button("Probar base + Apify", width="stretch"):
            d = storage.diagnose()
            _tok = config.APIFY_TOKEN
            st.write(f"**Backend:** {d['backend']}")
            st.write(f"**Token Apify:** {'✅ presente' if _tok else '❌ falta'} · "
                     f"longitud **{len(_tok)}** (debe ser 46) · empieza por apify_api_: "
                     f"{'✅' if _tok.startswith('apify_api_') else '❌'}")
            st.write(f"**IG_USERNAME configurado:** {'✅' if d['username_configurado'] else '❌'}")
            st.write(f"**Escritura:** {'✅' if d['write_ok'] else '❌'} · "
                     f"**Lectura:** {'✅' if d['read_ok'] else '❌'}")
            if d.get("error"):
                st.error(str(d["error"])[:600])
            try:
                from apify import InstagramSource
                items = InstagramSource(config.APIFY_TOKEN).fetch_profile()
                st.success(f"Apify OK · {len(items)} resultado(s)")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Apify falló: {exc}")

    with st.expander("📥 Importar snapshot histórico (JSON)"):
        st.caption("Sube un export de seguidores/seguidos (p. ej. tu snapshot de octubre).")
        up = st.file_uploader("Archivo .json", type=["json"], key="snapshot_up")
        if up is not None and st.button("Importar snapshot", width="stretch"):
            try:
                payload = json.loads(up.getvalue().decode("utf-8"))
                res = storage.import_snapshot(payload)
                st.session_state["flash"] = {
                    "ok": True,
                    "message": (
                        f"Snapshot importado ({res['captured_at'][:10]}): "
                        f"{res['followers']} seguidores · {res['following']} seguidos"
                    ),
                    "errors": [],
                }
            except Exception as exc:  # noqa: BLE001
                st.session_state["flash"] = {
                    "ok": False, "message": f"Error al importar: {exc}", "errors": []}
            st.rerun()

    with st.expander("🔎 Enriquecer perfiles (Apify)"):
        st.caption("Descarga bios y categorías de las cuentas que sigues, para "
                   "clasificarlas mejor. Consume crédito de Apify por cada cuenta.")
        enrich_n = st.number_input("Cuántas cuentas enriquecer", min_value=10,
                                   max_value=1000, value=100, step=10)
        if st.button("Enriquecer ahora", width="stretch"):
            if not config.APIFY_TOKEN:
                st.session_state["flash"] = {
                    "ok": False, "message": "Falta APIFY_TOKEN en los secretos.", "errors": []}
            else:
                with st.spinner("Descargando perfiles vía Apify…"):
                    try:
                        from apify import InstagramSource
                        members = analytics.relation_members(
                            storage.get_relation_history(), "following")
                        done = storage.get_account_profiles()
                        pend = [m.get("username") for m in members
                                if m.get("username")
                                and m["username"].lower() not in done]
                        pend = pend[:int(enrich_n)]
                        if not pend:
                            st.session_state["flash"] = {
                                "ok": True, "message": "Todas las cuentas ya están enriquecidas.",
                                "errors": []}
                        else:
                            items = InstagramSource(config.APIFY_TOKEN).fetch_profiles(pend)
                            n = storage.save_account_profiles(items)
                            st.session_state["flash"] = {
                                "ok": True,
                                "message": f"Perfiles enriquecidos: {n} de {len(pend)} solicitados.",
                                "errors": []}
                    except Exception as exc:  # noqa: BLE001
                        st.session_state["flash"] = {
                            "ok": False, "message": f"Error al enriquecer: {exc}", "errors": []}
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

# --- Actividad diaria --------------------------------------------------------

st.subheader("📅 Actividad diaria")
ingest = data["ingest"]
digest_today = analytics.daily_digest(
    data["events"], posts, data["comments"], data["mentions"], ingest)

d1, d2, d3, d4, d5 = st.columns(5)
d1.metric("Posts hoy", digest_today["posts"])
d2.metric("Comentarios hoy", digest_today["comments_received"])
d3.metric("Menciones hoy", digest_today["mentions_received"])
d4.metric("Seguidores hoy", f"{digest_today['net_followers']:+d}",
          delta=f"+{digest_today['new_followers']} / −{digest_today['lost_followers']}")
d5.metric("Última ingesta",
          (ingest[0]["ts"][:16].replace("T", " ") if ingest else "—"))

activity = analytics.activity_series(
    data["events"], posts, data["comments"], data["mentions"], days=14)
if activity:
    st.plotly_chart(analytics.fig_activity(activity), width="stretch")

with st.expander("🗂️ Fuentes de datos consumidas (ingest log)"):
    if ingest:
        por_fuente = {}
        for i in ingest:
            key = i.get("source") or "?"
            por_fuente[key] = por_fuente.get(key, 0) + 1
        st.caption("Ingestas por fuente: " + " · ".join(
            f"**{k}**: {v}" for k, v in sorted(por_fuente.items())))
        st.dataframe([{
            "Cuándo": (i.get("ts") or "")[:19].replace("T", " "),
            "Fuente": i.get("source"),
            "Detalle": i.get("detail"),
            "Registros": i.get("items"),
            "Estado": "✅" if i.get("status") == "ok" else "⚠️",
            "Mensaje": (i.get("message") or "")[:90],
        } for i in ingest[:200]], width="stretch", hide_index=True)
    else:
        st.caption("Sin ingestas registradas todavía.")

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
        "ℹ️ El plan gratuito de Apify devuelve solo la **primera página** de cada lista. "
        "Si importas un snapshot histórico más completo (p. ej. tu export de octubre), "
        "las **bajas** al comparar listas de distinto alcance pueden ser un artefacto del muestreo."
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

# --- Retención y churn -------------------------------------------------------

st.subheader("📈 Retención y churn")
retentions = [r for r in (
    analytics.follow_retention(relation_history, "follower"),
    analytics.follow_retention(relation_history, "following"),
) if r]
if retentions:
    st.plotly_chart(analytics.fig_retention(retentions), width="stretch")
    for r in retentions:
        nombre = "Seguidores" if r["relation_type"] == "follower" else "Seguidos"
        st.caption(
            f"**{nombre}**: {r['retained']} de {r['first_count']} se mantienen "
            f"({r['retention_pct']}%) · {r['dropped']} bajas · {r['added']} nuevas "
            f"(de {r['first_date'][:10]} a {r['latest_date'][:10]})"
        )
else:
    st.caption("Necesitas al menos dos fotos de las listas (importa un snapshot y sincroniza).")

churn = analytics.relation_churn(events)
if churn:
    st.markdown("**Cuentas con más movimiento (serial follow/unfollow)**")
    st.dataframe([{
        "Usuario": c["username"], "Nombre": c["full_name"] or "",
        "Bajas": c["lost_count"], "Altas": c["new_count"],
        "Eventos": c["total"], "Último": (c["last_event"] or "")[:10],
    } for c in churn[:20]], width="stretch", hide_index=True)

re_follow = analytics.re_follows(events)
if re_follow:
    st.markdown("**Vuelven a aparecer (baja → alta)**")
    st.dataframe([{
        "Usuario": r["username"], "Nombre": r["full_name"] or "",
        "Eventos": r["eventos"], "Último": (r["ultimo"] or "")[:10],
    } for r in re_follow[:20]], width="stretch", hide_index=True)

spikes = [a for a in analytics.unfollow_anomalies(events) if a["is_spike"]]
if spikes:
    st.warning("⚠️ Picos de bajas detectados: "
               + ", ".join(f"{a['date']} ({a['count']})" for a in spikes))

st.divider()

# --- Categorías --------------------------------------------------------------

st.subheader("📂 Categorías de cuentas")
profiles = data["profiles"]
cat_following = analytics.category_distribution(following_members, profiles)
cat_followers = analytics.category_distribution(followers_members, profiles)
if cat_following or cat_followers:
    col_g, col_f = st.columns(2, gap="large")
    with col_g:
        st.markdown("**A quién sigues**")
        if cat_following:
            st.plotly_chart(analytics.fig_categories(cat_following), width="stretch")
            st.dataframe(cat_following, width="stretch", hide_index=True)
    with col_f:
        st.markdown("**Quién te sigue**")
        if cat_followers:
            st.plotly_chart(analytics.fig_categories(cat_followers), width="stretch")
            st.dataframe(cat_followers, width="stretch", hide_index=True)
    st.caption(
        "Clasificación por palabras clave del username/nombre"
        + (" y biografía (perfiles enriquecidos)." if profiles
           else ". Usa “🔎 Enriquecer perfiles” para mejorar la precisión con las bios.")
    )
else:
    st.caption("Sin cuentas para categorizar todavía.")

st.divider()

# --- Historial de interacciones ----------------------------------------------

st.subheader("🤝 Historial de interacciones por cuenta")
inter_idx = analytics.interaction_index(
    relation_history, events, posts, data["comments"], data["mentions"],
    exclude=(config.USERNAME,),
)
inter_map = {i["key"]: i for i in inter_idx}
if inter_idx:
    st.caption("Combina follows/unfollows, menciones que **haces**, menciones que **te hacen** "
               "y comentarios que **recibes** (las señales públicas disponibles).")
    st.dataframe([{
        "Usuario": i["username"],
        "Follows/Unfollows": i["follow_events"],
        "Menciones que haces": i["mentioned_by_me"],
        "Menciones que te hacen": i["mentions_me"],
        "Comentarios recibidos": i["comments_received"],
        "Total": i["total"],
        "Última": i["last"],
    } for i in inter_idx[:300]], width="stretch", hide_index=True)
else:
    st.caption("Sin interacciones registradas todavía.")

st.divider()

# --- Ficha 360 ---------------------------------------------------------------

st.subheader("🔎 Ficha 360 por cuenta")
all_keys = sorted({
    (m.get("username") or "") for m in (followers_members + following_members)
    if m.get("username")
})
if all_keys:
    query = st.text_input("Buscar cuenta (username)", "")
    options = [k for k in all_keys if query.lower() in k.lower()] if query else all_keys
    if options:
        chosen_acc = st.selectbox("Cuenta", options[:500])
        card = analytics.account_card(relation_history, events, profiles, chosen_acc)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Te sigue", "✅" if card["is_follower"] else "❌")
        k2.metric("La sigues", "✅" if card["is_following"] else "❌")
        k3.metric("Mutuo", "✅" if card["mutual"] else "❌")
        k4.metric("Fotos donde aparece", card["snapshots"])
        inter = inter_map.get(str(chosen_acc).strip().lstrip("@").lower())
        if inter:
            i1, i2, i3, i4 = st.columns(4)
            i1.metric("Follows/Unfollows", inter["follow_events"])
            i2.metric("Menciones que haces", inter["mentioned_by_me"])
            i3.metric("Menciones que te hacen", inter["mentions_me"])
            i4.metric("Comentarios recibidos", inter["comments_received"])
        st.markdown(
            f"**@{config.mask(card['username'])}**"
            + (f" · {config.mask(card['full_name'])}" if card.get("full_name") else "")
            + (f" · 🏷️ {card['category']}" if card.get("category") else "")
        )
        if card.get("biography"):
            st.caption(config.mask(card["biography"]))
        st.caption(
            f"Visto desde {(card['first_seen'] or '')[:10]} hasta {(card['last_seen'] or '')[:10]}"
            + (f" · 🔗 {config.mask(card['profile_url'])}" if card.get("profile_url") else "")
        )
        if card["events"]:
            st.markdown("**Historial de cambios**")
            event_labels_card = {
                "new_follower": "🟢 Nuevo seguidor", "lost_follower": "🔻 Te dejó de seguir",
                "new_following": "🟢 Nuevo seguido", "lost_following": "🔻 Dejaste de seguir",
            }
            st.dataframe([{
                "Fecha": (e.get("detected_at") or "")[:10],
                "Evento": event_labels_card.get(e.get("event_type"), e.get("event_type")),
            } for e in card["events"]], width="stretch", hide_index=True)
        else:
            st.caption("Sin cambios registrados para esta cuenta.")
    else:
        st.caption("Ninguna cuenta coincide con la búsqueda.")
else:
    st.caption("Importa un snapshot o sincroniza para tener cuentas.")

st.divider()

# --- Recomendador de limpieza ------------------------------------------------

st.subheader("🧹 Recomendador de limpieza")
clean = analytics.cleaning_suggestions(relation_history)
if clean:
    st.caption(f"{len(clean)} cuentas que sigues y no te siguen de vuelta.")
    st.dataframe([{
        "Usuario": c.get("username"), "Nombre": c.get("full_name") or "",
        "Verificado": "✅" if c.get("is_verified") else "",
    } for c in clean[:200]], width="stretch", hide_index=True)
else:
    st.caption("Sin sugerencias (o faltan datos de las listas).")

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


st.divider()

# --- Cuentas destacadas (watchlist) ------------------------------------------

st.subheader("⭐ Cuentas destacadas")
watch = storage.get_watchlist()
if watch:
    watch_tabs = st.tabs([f"@{w['username']}" for w in watch])
    for wtab, w in zip(watch_tabs, watch):
        with wtab:
            rep = analytics.account_report(
                data["relation_history"], data["events"], posts,
                data["comments"], data["mentions"], data["profiles"], w["username"])
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Te sigue", "✅" if rep["is_follower"] else "❌")
            c2.metric("La sigues", "✅" if rep["is_following"] else "❌")
            c3.metric("Señales totales", rep["total_signals"])
            c4.metric("Fotos donde aparece", rep["snapshots"])
            st.markdown(
                f"**@{config.mask(rep['username'])}**"
                + (f" · {config.mask(rep['full_name'])}" if rep.get("full_name") else "")
                + (f" · 🏷️ {rep['category']}" if rep.get("category") else "")
                + f" · 🔗 {config.mask(rep['profile_url'])}"
            )
            if rep.get("biography"):
                st.caption(config.mask(rep["biography"]))
            s1, s2, s3 = st.columns(3)
            s1.metric("La mencionas", len(rep["my_mentions"]))
            s2.metric("Te menciona", len(rep["their_mentions"]))
            s3.metric("Te comenta", len(rep["their_comments"]))
            if rep.get("enriched"):
                e1, e2, e3, e4 = st.columns(4)
                e1.metric("Seguidores", f"{rep['profile_followers']:,}"
                          if rep.get("profile_followers") else "—")
                e2.metric("Publicaciones", f"{rep['profile_posts']:,}"
                          if rep.get("profile_posts") else "—")
                e3.metric("Verificada", "✅" if rep.get("verified") else "❌")
                e4.metric("Privada", "🔒" if rep.get("private") else "—")
                if rep.get("latest_posts"):
                    st.markdown("**Sus últimos posts**")
                    st.dataframe([{
                        "Fecha": (post.get("timestamp") or "")[:10],
                        "Tipo": post.get("type") or "",
                        "Caption": config.mask((post.get("caption") or "").replace("\n", " ")[:100]),
                        "Likes": post.get("likesCount"),
                        "URL": post.get("url") or "",
                    } for post in rep["latest_posts"][:12]], width="stretch", hide_index=True)
            else:
                st.caption("Sin datos de perfil todavía: pulsa «Enriquecer destacadas (Apify)» "
                           "para traer su bio, seguidores y sus últimos posts.")
            if rep["timeline"]:
                timeline_labels = {
                    "new_follower": "🟢 Te empezó a seguir",
                    "lost_follower": "🔻 Te dejó de seguir",
                    "new_following": "🟢 La empezaste a seguir",
                    "lost_following": "🔻 Dejaste de seguir",
                    "yo_la_menciono": "📣 La mencionaste",
                    "me_menciona": "🏷️ Te mencionó",
                    "me_comenta": "💬 Te comentó",
                }
                st.dataframe([{
                    "Fecha": t["date"],
                    "Señal": timeline_labels.get(t["what"], t["what"]),
                    "Detalle": config.mask(t["detail"]),
                } for t in rep["timeline"]], width="stretch", hide_index=True)
            else:
                st.caption("Sin señales registradas todavía. Sincroniza o usa «Enriquecer destacadas».")

            wi = analytics.watch_interactions(
                data["external_posts"], data["external_comments"],
                data["comments"], w["username"], config.USERNAME,
                story_mentions=data["story_mentions"])
            st.markdown("#### 💬 Interacción en publicaciones")
            wm1, wm2, wm3 = st.columns(3)
            wm1.metric("Tú comentas sus posts", len(wi["my_comments_on_theirs"]))
            wm2.metric("Ellos comentan tus posts", len(wi["their_comments_on_mine"]))
            wm3.metric("Sus posts analizados", len(wi["their_posts"]))
            if wi["my_comments_on_theirs"]:
                st.markdown("**Tus comentarios en sus publicaciones**")
                st.dataframe([{
                    "Fecha": (c.get("timestamp") or "")[:10],
                    "Comentario": config.mask(c.get("text") or ""),
                    "Post": c.get("post_url") or "",
                } for c in wi["my_comments_on_theirs"]], width="stretch", hide_index=True,
                    column_config={"Post": st.column_config.LinkColumn("Post")})
            if wi["their_comments_on_mine"]:
                st.markdown("**Sus comentarios en tus publicaciones**")
                st.dataframe([{
                    "Fecha": (c.get("timestamp") or "")[:10],
                    "Comentario": config.mask(c.get("text") or ""),
                } for c in wi["their_comments_on_mine"]], width="stretch", hide_index=True)

            st.markdown("#### 📸 Menciones en historias")
            sm1, sm2 = st.columns(2)
            sm1.metric("Ellas te mencionan", len(wi["stories_from_them"]))
            sm2.metric("Tú las mencionas", len(wi["stories_of_me"]))
            me_key = (config.USERNAME or "").strip().lstrip("@").lower()
            story_rows = [{
                "Fecha": (s.get("timestamp") or "")[:10],
                "Dirección": ("Ellas → ti"
                              if (s.get("mentioned_username") or "").lower() == me_key
                              else "Tú → ellas"),
                "Historia de": s.get("source_username"),
                "Menciona a": s.get("mentioned_username"),
                "Enlace": s.get("url") or "",
            } for s in (wi["stories_from_them"] + wi["stories_of_me"])]
            if story_rows:
                st.dataframe(story_rows, width="stretch", hide_index=True,
                             column_config={"Enlace": st.column_config.LinkColumn("Enlace")})
            else:
                st.caption("Sin menciones de historias registradas. Las de **ellas** requieren "
                           "la burner (o sesión); las **tuyas**, tu sesión: son efímeras y "
                           "privadas. Puedes importarlas con el JSON del gestor de abajo.")

            # --- Threads (público, sin sesión) ---
            st.markdown("#### 🧵 Threads (público)")
            tposts = [t for t in data["threads"]
                      if (t.get("username") or "").lower() == w["username"].lower()]
            me_threads = (config.USERNAME or "").strip().lstrip("@").lower()
            t_mentions = [t for t in tposts
                          if me_threads and me_threads in (t.get("text") or "").lower()]
            tm1, tm2, tm3 = st.columns(3)
            tm1.metric("Posts recientes", len(tposts))
            tm2.metric("Seguidores en Threads", (tposts[0].get("followers") or 0) if tposts else 0)
            tm3.metric("Te mencionan", len(t_mentions))
            if tposts:
                st.dataframe([{
                    "Fecha": (t.get("taken_at") or "")[:10],
                    "Texto": (t.get("text") or "")[:130],
                    "Likes": t.get("like_count"),
                    "Enlace": t.get("url") or "",
                } for t in tposts], width="stretch", hide_index=True,
                    column_config={"Enlace": st.column_config.LinkColumn("Enlace")})
            else:
                st.caption("Sin datos de Threads. Pulsa **«🧵 Sincronizar Threads»** en el "
                           "gestor de abajo (solo funciona si su perfil es público).")

            if wi["their_posts"]:
                with st.expander(f"Ver sus publicaciones ({len(wi['their_posts'])})"):
                    st.dataframe([{
                        "Fecha": (p.get("timestamp") or "")[:10],
                        "Caption": config.mask((p.get("caption") or "").replace("\n", " ")[:90]),
                        "Likes": p.get("likes_count"),
                        "Comentarios": p.get("comments_count"),
                        "URL": p.get("url") or "",
                    } for p in wi["their_posts"][:30]], width="stretch", hide_index=True,
                        column_config={"URL": st.column_config.LinkColumn("URL")})
            if not (wi["my_comments_on_theirs"] or wi["their_comments_on_mine"] or wi["their_posts"]):
                st.caption("Sin interacción descargada todavía → usa "
                           "«🔄 Sincronizar interacciones» abajo.")

with st.expander("➕ Gestionar cuentas destacadas"):
    add_name = st.text_input("Añadir cuenta (username, sin @)", "", key="watch_add")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Añadir a destacadas", width="stretch"):
            if add_name.strip():
                storage.add_watch_accounts([add_name.strip()])
                st.session_state["flash"] = {
                    "ok": True, "message": f"Cuenta añadida: {add_name.strip()}", "errors": []}
                st.rerun()
    with col_b:
        if st.button("Enriquecer destacadas (Apify)", width="stretch"):
            if not config.APIFY_TOKEN:
                st.session_state["flash"] = {
                    "ok": False, "message": "Falta APIFY_TOKEN.", "errors": []}
            else:
                with st.spinner("Descargando perfiles…"):
                    try:
                        from apify import InstagramSource
                        items = InstagramSource(config.APIFY_TOKEN).fetch_profiles(
                            [w["username"] for w in watch])
                        n = storage.save_account_profiles(items)
                        st.session_state["flash"] = {
                            "ok": True, "message": f"Perfiles actualizados: {n}", "errors": []}
                    except Exception as exc:  # noqa: BLE001
                        st.session_state["flash"] = {
                            "ok": False, "message": f"Error: {exc}", "errors": []}
            st.rerun()
    if st.button("🔄 Sincronizar interacciones (posts + comentarios)", width="stretch"):
        if not config.APIFY_TOKEN:
            st.session_state["flash"] = {
                "ok": False, "message": "Falta APIFY_TOKEN.", "errors": []}
        else:
            with st.spinner("Descargando sus posts y comentarios… (puede tardar varios minutos)"):
                try:
                    from sync import do_watch_sync
                    res = do_watch_sync(
                        token=config.APIFY_TOKEN,
                        accounts=[w["username"] for w in watch],
                        posts_per_account=20, comments_per_post=20)
                    st.session_state["flash"] = {
                        "ok": True,
                        "message": (f"Interacciones actualizadas: {res['posts']} posts y "
                                    f"{res['comments']} comentarios de {res['accounts']} cuentas."),
                        "errors": list(res.get("errors", [])),
                    }
                except Exception as exc:  # noqa: BLE001
                    st.session_state["flash"] = {
                        "ok": False, "message": f"Error: {exc}", "errors": []}
        st.rerun()
    if st.button("🧵 Sincronizar Threads (público)", width="stretch"):
        if not config.APIFY_TOKEN:
            st.session_state["flash"] = {
                "ok": False, "message": "Falta APIFY_TOKEN.", "errors": []}
        else:
            with st.spinner("Consultando Threads… (solo perfiles públicos)"):
                try:
                    from sync import do_threads_sync
                    res = do_threads_sync(token=config.APIFY_TOKEN,
                                          accounts=[w["username"] for w in watch])
                    st.session_state["flash"] = {
                        "ok": True, "message": res["message"],
                        "errors": list(res.get("errors", [])),
                    }
                except Exception as exc:  # noqa: BLE001
                    st.session_state["flash"] = {
                        "ok": False, "message": f"Error: {exc}", "errors": []}
        st.rerun()
    st.markdown("**📥 Importar menciones de historias (JSON)**")
    st.caption('Formato: [{"source_username":"cuenta","mentioned_username":"tu_usuario",'
               '"direction":"them_to_me","url":"https://instagram.com/stories/...",'
               '"timestamp":"2026-01-01T00:00:00Z"}]')
    up_stories = st.file_uploader("Archivo .json de historias", type=["json"], key="stories_up")
    if up_stories is not None and st.button("Importar historias", width="stretch"):
        try:
            payload = json.loads(up_stories.getvalue().decode("utf-8"))
            n = storage.import_story_mentions(payload)
            st.session_state["flash"] = {
                "ok": True, "message": f"Menciones de historias importadas: {n}", "errors": []}
        except Exception as exc:  # noqa: BLE001
            st.session_state["flash"] = {
                "ok": False, "message": f"Error al importar historias: {exc}", "errors": []}
        st.rerun()
    if watch:
        remove_name = st.selectbox("Quitar de destacadas",
                                   [w["username"] for w in watch], key="watch_rm")
        if st.button("Quitar cuenta", width="stretch"):
            storage.remove_watch_account(remove_name)
            st.rerun()

st.divider()

# --- Índice de afinidad ------------------------------------------------------

st.subheader("🏆 Índice de afinidad")
watch_aff = storage.get_watchlist()
if watch_aff:
    def _card_for(username):
        return analytics.account_report(
            data["relation_history"], data["events"], posts,
            data["comments"], data["mentions"], data["profiles"], username)

    def _inter_for(username):
        return analytics.watch_interactions(
            data["external_posts"], data["external_comments"],
            data["comments"], username, config.USERNAME,
            story_mentions=data["story_mentions"])

    aff_rows = analytics.affinity_table(watch_aff, _card_for, _inter_for)
    st.dataframe([{
        "Cuenta": f"@{r['username']}",
        "Afinidad": r["score"],
        "Señales": r["total_signals"],
        "Última señal": (r["last_signal"] or "")[:10],
    } for r in aff_rows], width="stretch", hide_index=True)

    st.caption("Pesos: historias ×4 · follows, menciones y comentarios ×3 · "
               "menciones en posts ×2. Solo cuenta señales públicas.")

    with st.expander("Ver el desglose de cada cuenta"):
        for r in aff_rows:
            st.markdown(f"**@{config.mask(r['username'])} — {r['score']} puntos**")
            st.dataframe([{
                "Señal": c["signal"],
                "Cantidad": c["count"],
                "Peso": c["weight"],
                "Puntos": c["points"],
            } for c in r["components"]], width="stretch", hide_index=True)
else:
    st.caption("Añade cuentas destacadas para calcular su afinidad.")

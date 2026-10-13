# Roadmap y estado — Centro de monitoreo IG

> Documento vivo. Actualízalo al cerrar cada sesión de trabajo.
> Última actualización: sesión de octubre 2026.

## ✅ Hecho

- Pipeline con **Apify** (perfil, posts, seguidores, seguidos, comentarios, menciones).
- **Persistencia en Turso** (nube) + SQLite local. Desplegado en **Streamlit Cloud**.
- **13 secciones** en el panel: KPIs, gráficos, seguidores/seguidos con historial,
  cambios (unfollows), mutuales, calidad de audiencia, retención y churn,
  categorías, ficha 360, limpieza, interacciones, comentarios, menciones,
  destacadas (watchlist), actividad diaria + ingest log, informe Excel.
- **Snapshot histórico** de octubre importado (50 seguidores / 898 seguidos).
- **Alertas por Telegram** + **rutina diaria** (`daily.py`).
- **Privacidad**: username purgado del repo, panel muestra "IG FV", textos enmascarados.
- **Scripts locales con la burner** (3 variantes: API, Playwright, método humano).
- **Escáner de destacadas** (`burner_highlights.py`): busca menciones tuyas en las
  historias destacadas (el único sitio donde sobrevive una mención de historia,
  con su **fecha original**).
- **🏆 Índice de afinidad**: puntaje por cuenta destacada combinando todas las
  señales públicas (historias ×4, follows/menciones/comentarios ×3, menciones
  en posts ×2), con desglose por señal.
- **Estado de hoy**: token de Apify ✅ · sync ✅ · rutina cron ✅ (05:00 con `--watch`).

## 🔴 Bloqueadores actuales

| # | Bloqueador | Impacto | Cómo se resuelve |
|---|---|---|---|
| 1 | **Plan gratis de Apify** (~50 por lista) | Datos incompletos, watchlist vacía | Curtir la burner o plan de pago |
| 2 | **Burner con 429 en la API** | Sin listas completas | El **método humano** (`burner_human.py`) evita la API |
| 3 | **Selectores de Instagram** | No abre las listas todavía | `--debug` para ver qué encuentra y ajustar |
| 4 | **Historias/DMs borrados** | Interacciones irrecuperables | Solo quedan las **destacadas** |

## 🎯 Pendiente priorizado

### P0 — Desbloquear (5 min)
- [ ] Reboot de la app + diagnóstico → confirmar el token de Apify.
- [ ] Primera sincronización real.

### P1 — Automatizar (15 min)
- [ ] Activar la rutina diaria (`./install_cron.sh` o GitHub Actions).
- [ ] Añadir los secretos de Telegram para recibir el resumen.

### P2 — Datos de las 5 cuentas destacadas
- [ ] **A)** Sincronizar interacciones (posts + comentarios) con Apify. *Funciona ya.*
- [ ] **B)** Enriquecer sus perfiles (bio, seguidores, últimos posts). *Funciona ya, centavos.*
- [ ] **C)** `burner_human.py` para listas completas + historias. *Tras enfriar el 429.*

### P3 — Expansión pública (sin usar la cuenta propia)
- [ ] **Threads** de las 5 cuentas (público, sin login) — mayor valor.
- [ ] Transcripción de reels (`apify/instagram-reel-scraper`).
- [ ] Ads Library (`apify/facebook-ads-scraper`) para inteligencia competitiva.
- [ ] Hashtags y lugares.

### P4 — Ideas exploradas y descartadas (documentado)
- ❌ **Datos privados propios** (reels vistos, búsquedas, tiempo de uso, DMs,
  likes dados): imposibles sin exportar la cuenta. El usuario decidió no usarla.
- ⚠️ **agent-reach**: auditado → limpio, sin backdoors, pero **Instagram fue
  removido** (bloqueado por Meta) → no ahorra Apify. Añade npm globales, Docker
  y servicios terceros (Jina, Exa) + cookies. Solo viable para X/Reddit/YouTube
  en local. Ver sección "Seguridad" abajo.

## 🤖 Automatizaciones

| Tarea | Herramienta | Estado |
|---|---|---|
| Sync diaria + resumen Telegram | `daily.py` | ✅ listo, ⏳ sin activar |
| Cron local | `install_cron.sh` | ✅ listo |
| GitHub Actions | `.github/workflows/daily.yml` | ⏳ requiere scope `workflow` del token |
| Interacciones de destacadas | `daily.py --watch` | ✅ listo |
| Alertas de unfollow / reel viral | `notify.py` | ✅ listo (requiere Telegram) |

## 🔐 Notas de seguridad

- El proyecto tiene **4 dependencias directas** (streamlit, plotly, openpyxl, libsql).
- **El núcleo de datos no usa ninguna**: habla con Apify vía `urllib` (librería estándar).
- **No** instala nada global, **no** usa Docker, **no** envía datos a terceros
  (solo `api.apify.com` y, si se configura, Telegram).
- **No** guarda cookies ni sesiones.
- Los scripts de la burner sí usan `requests`/`browser_cookie3`/`playwright`,
  pero son **locales y opcionales**.

## 🧭 Cómo retomar

```bash
cd ~/Desktop/School/DSWS/ig-monitor
python3 daily.py --dry-run --no-sync   # ver el resumen sin tocar nada
streamlit run app.py                    # abrir el panel local
```

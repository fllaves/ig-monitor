# Despliegue del panel en la nube (Streamlit Community Cloud)

Este panel se puede dejar **siempre disponible** en Internet, accesible desde
cualquier navegador o celular, sin ejecutar nada en tu Mac.

## Por qué se necesita una base en la nube

Streamlit Cloud **no conserva los archivos** entre reinicios: si usamos la base
SQLite local (`data/*.db`), **perderías todo el historial** en cada reinicio.
Por eso usamos **Turso** (libSQL), una base SQLite en la nube con plan gratuito.

---

## Paso 1 — Subir el código a GitHub

1. Crea un repositorio **privado** en GitHub (p. ej. `ig-monitor`).
2. Sube la carpeta `ig-monitor/`:
   ```bash
   cd ig-monitor
   git init
   git add .
   git commit -m "Panel de monitoreo de Instagram"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/ig-monitor.git
   git push -u origin main
   ```
   > `.gitignore` ya excluye `.env`, `.streamlit/secrets.toml` y `data/`, así que
   > tu token y tus datos no se suben.

## Paso 2 — Crear la base en Turso (gratis)

Opción A (web, más fácil):
1. Entra en [turso.tech](https://turso.tech) y crea una cuenta.
2. Crea una base de datos (p. ej. `instagram-monitor`).
3. Copia la **URL** (`libsql://instagram-monitor-tu-usuario.turso.io`) y genera un
   **auth token**.

Opción B (CLI):
```bash
brew install tursodatabase/tap/turso
turso auth signup
turso db create instagram-monitor
turso db show instagram-monitor        # → te da la URL
turso db tokens create instagram-monitor  # → te da el auth token
```

## Paso 3 — Desplegar en Streamlit Community Cloud

1. Entra en [share.streamlit.io](https://share.streamlit.io) con tu cuenta de GitHub.
2. **New app** → elige tu repositorio `ig-monitor`.
3. **Main file path**: `app.py`.
4. En **Advanced settings → Secrets**, pega:

   ```toml
   APIFY_TOKEN = "apify_api_..."
   IG_USERNAME = "tu_usuario_ig"
   DISPLAY_NAME = "IG FV"
   DATABASE_URL = "libsql://tu-base.turso.io"
   DATABASE_AUTH_TOKEN = "tu-token-de-turso"
   ```

5. **Deploy**. Listo: tendrás una URL pública tipo
   `https://tu-app.streamlit.app`.

## Paso 4 — Sincronizar desde la nube

Dentro del panel en la nube, pulsa **"Sincronizar con Apify"** en la barra
lateral. Los datos quedan guardados en Turso y **persisten** entre reinicios.

> 💡 Para automatizarlo sin abrir el panel, usa el `cron` local con `sync.py`
> apuntando a `DATABASE_URL` (ver README).

## Notas

- La primera vez, la base de Turso está vacía: el panel creará las tablas solo.
- El plan gratuito de Apify sigue limitando las listas a ~50 cuentas.
- Si prefieres no usar Turso, puedes dejar `DATABASE_URL` vacío y usar SQLite
  local, pero **no** persistirá en la nube.

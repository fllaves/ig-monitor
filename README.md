# 📊 Centro de monitoreo de Instagram

Dashboard web interactivo que convierte tu cuenta pública de Instagram en un
centro de informes sofisticado: extrae datos con **Apify**, acumula historial
local (SQLite) y muestra tendencias, KPIs y análisis de engagement.

![Stack](https://img.shields.io/badge/Python-3.9%2B-blue) ![Streamlit](https://img.shields.io/badge/Streamlit-dashboard-red) ![Apify](https://img.shields.io/badge/Apify-instagram--scraper-orange)

## Qué hace

- Descarga el **perfil** (seguidores, seguidos, bio, verificación…) y las
  **publicaciones** (likes, comentarios, vistas, hashtags, fechas…) desde
  Apify usando el Actor oficial [`apify/instagram-scraper`](https://apify.com/apify/instagram-scraper).
- Descarga las **listas de seguidores y seguidos** con el Actor
  [`apify/instagram-followers-following-scraper`](https://apify.com/apify/instagram-followers-following-scraper),
  con su **historial por fecha**.
- **Detecta cambios entre sincronizaciones**: quién te dejó de seguir, a quién
  dejaste de seguir, nuevos seguidores y nuevos seguidos, con un **historial
  persistente** de cada evento (quién y cuándo).
- **Seguidores mutuos (mutuals)**: cruza ambas listas para ver quién te sigue y
  no sigues de vuelta, y viceversa.
- **Calidad de audiencia**: % de seguidores verificados/privados y detección de
  cuentas sospechosas (sin nombre ni foto).
- **Comentarios y menciones**: descarga comentarios de tus posts (con análisis
  de sentimiento y fans más activos) y publicaciones donde te etiquetan.
- **Alertas por Telegram**: aviso automático cuando alguien te deja de seguir o
  un reel supera un umbral de reproducciones.
- **Informe semanal en Excel** (.xlsx) con todas las hojas (resumen, posts,
  seguidores, seguidos, cambios, comentarios, menciones).
- Guarda cada sincronización en **SQLite local** y conserva el **JSON crudo**
  de cada item para no perder ningún campo.
- Muestra un **dashboard interactivo** (Streamlit + Plotly):
  - KPIs: seguidores (con delta), seguidos, publicaciones, likes/comentarios
    promedio y engagement rate.
  - Crecimiento de seguidores, publicaciones por mes, horario de publicación,
    tipo de contenido, hashtags más usados, top publicaciones y
    likes vs. comentarios.
  - Sección **Seguidores y seguidos** con altas/bajas, historial y mutuales.
  - Tabla de publicaciones con filtro y **exportación a CSV**.

## Requisitos

- Python 3.9 o superior.
- Una cuenta gratuita de [Apify](https://apify.com) y su **API token**.

## Instalación

```bash
cd ig-monitor

# 1) Entorno virtual + dependencias
python3 -m venv .venv
source .venv/bin/activate            # en Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2) Configura tu token
cp .env.example .env
#   edita .env y pega tu APIFY_TOKEN (https://console.apify.com/settings/integrations)
```

## Uso

### Opción A — Dashboard interactivo (recomendada)

```bash
streamlit run app.py
```

Se abre en tu navegador. Desde la barra lateral puedes:

- **Sincronizar con Apify**: descarga los datos reales de tu cuenta.
- **Cargar datos demo**: para previsualizar sin token.
- **Reiniciar datos**: borra el historial local.

> 💡 Sincroniza una vez al día (o por semana) y verás crecer las series de
> seguidores y engagement.

### Opción B — Sincronizar por línea de comandos (para cron/automatizar)

```bash
python sync.py                     # sincroniza con Apify
python sync.py --demo              # datos de demostración
python sync.py --limit 200         # limita publicaciones
python sync.py --followers-limit 500 --following-limit 500
```

Puedes programarlo con `cron` (macOS/Linux) para que se ejecute solo:

```cron
0 9 * * * cd /ruta/a/ig-monitor && .venv/bin/python sync.py >> sync.log 2>&1
```

## Panel siempre disponible en la nube

Para abrir el panel desde cualquier navegador/celular sin ejecutar nada, puedes
desplegarlo gratis en **Streamlit Community Cloud** con una base en **Turso**.
Ver la guía completa en [`DEPLOY.md`](DEPLOY.md).

O, en local, con un solo clic:

```bash
./run.sh        # crea el entorno la primera vez y abre http://localhost:8501
```

## Estructura

```
ig-monitor/
├── app.py          # Dashboard Streamlit
├── sync.py         # Sincronización (CLI + función reutilizable)
├── apify.py        # Cliente ligero de la API REST de Apify (urllib)
├── storage.py      # Persistencia en SQLite (historial acumulado)
├── analytics.py    # Métricas y figuras de Plotly
├── demo.py         # Datos de demostración
├── config.py       # Configuración (lee .env)
└── requirements.txt
```

## Datos que extrae Apify (cuenta pública)

| Dimensión | Campos |
|---|---|
| Perfil | `followersCount`, `followsCount`, `postsCount`, `biography`, `verified`, `businessCategoryName`, `profilePicUrl`, `externalUrl` |
| Publicaciones | `caption`, `likesCount`, `commentsCount`, `videoPlayCount`, `videoViewCount`, `timestamp`, `type`, `productType`, `hashtags`, `mentions`, `url`, `displayUrl`, `videoUrl`, `images`, `childPosts`, `taggedUsers`, `musicInfo`, … |
| Seguidores / seguidos | `userId`, `username`, `fullName`, `profilePicUrl`, `isVerified`, `isPrivate`, `type` |

> Además de las columnas estructuradas, se guarda el **JSON crudo completo**
> de cada item, por lo que no se pierde ningún dato aunque no aparezca en la tabla.

## Notas importantes

- Apify **no recupera histórico retroactivo**: solo ves lo que Instagram muestra
  al momento de cada sincronización. Por eso el historial se acumula en local.
  Para detectar "quién te dejó de seguir", debes sincronizar **al menos dos veces**
  y comparar las listas.
- **Límite del plan gratuito**: el Actor de listas de seguidores/seguidos solo
  devuelve la **primera página (~20 cuentas, las más recientes)**. Para la lista
  completa necesitas un plan de pago (Starter o superior). El conteo total de
  seguidores (169.598) sí se ve en el perfil, pero la *lista* está limitada.
- El Actor cobra por resultado (≈$2.70 por 1.000 resultados en el plan gratis
  para publicaciones; las listas de seguidores tienen su propia tarifa por perfil).
  Monitorear una sola cuenta cuesta centavos por sincronización.
- Las métricas corresponden a lo que Instagram muestra a visitantes **sin sesión**;
  pueden diferir levemente de lo que ves con tu cuenta iniciada.
- Solo se accede a **datos públicos** de tu propia cuenta.

## Alertas por Telegram (opcional)

1. Habla con [@BotFather](https://t.me/BotFather) en Telegram y crea un bot → te da un **token**.
2. Escribe a tu bot y obtén tu **chat id** (p. ej. con [@userinfobot](https://t.me/userinfobot)).
3. Pon ambos valores en `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-...
   TELEGRAM_CHAT_ID=123456789
   ALERT_VIEWS_THRESHOLD=10000
   ```
Al sincronizar, recibirás un mensaje cuando alguien te deje de seguir o un reel
supere el umbral de reproducciones.

## Sobre los mensajes directos (DM)

Los DM son **privados** y no se pueden leer con scraping público (Apify trabaja
sin login). Las señales públicas de "quién interactúa contigo" que sí captura
este centro son: **comentarios**, **menciones/etiquetas** y **nuevos seguidores**.

## Solución de problemas

- **"Falta APIFY_TOKEN"**: crea `.env` y pega tu token, o define la variable
  de entorno `APIFY_TOKEN`.
- **El run termina en FAILED**: prueba con un `RESULTS_LIMIT` menor o verifica
  que la cuenta sigue siendo pública.
- **No aparecen gráficos**: asegúrate de haber instalado `plotly` y `streamlit`.

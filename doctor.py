"""Doctor: chequeo de salud del centro de monitoreo.

Responde en segundos a la única pregunta que importa: **¿el sistema está vivo
y acumulando datos, o está muerto sin que me entere?**

    python3 doctor.py              # chequeo completo
    python3 doctor.py --no-network  # sin llamar a Apify (offline)
    python3 doctor.py --json        # salida legible por máquina

Código de salida: 0 = todo bien · 1 = hay avisos · 2 = hay fallos críticos.
"""
import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

VERDE, AMBAR, ROJO, GRIS, FIN = "\033[92m", "\033[93m", "\033[91m", "\033[90m", "\033[0m"
if not sys.stdout.isatty():          # sin colores si la salida no es una terminal
    VERDE = AMBAR = ROJO = GRIS = FIN = ""
OK, WARN, FAIL, INFO = "✅", "⚠️ ", "❌", "·"

resultados = []


def add(estado: str, etiqueta: str, detalle: str = "") -> None:
    resultados.append({"estado": estado, "etiqueta": etiqueta, "detalle": detalle})
    color = {"ok": VERDE, "warn": AMBAR, "fail": ROJO, "info": GRIS}[estado]
    icono = {"ok": OK, "warn": WARN, "fail": FAIL, "info": INFO}[estado]
    print(f"  {color}{icono}{FIN} {etiqueta:<34} {GRIS}{detalle}{FIN}")


def seccion(titulo: str) -> None:
    print(f"\n{GRIS}── {titulo} {'─' * max(0, 58 - len(titulo))}{FIN}")


def hace(cuando: str) -> str:
    """Texto tipo 'hace 3 h' a partir de una fecha ISO."""
    try:
        dt = datetime.fromisoformat(str(cuando).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return "fecha desconocida"
    segundos = (datetime.now(timezone.utc) - dt).total_seconds()
    if segundos < 0:
        return "en el futuro (¿reloj?)"
    for unidad, factor in (("d", 86400), ("h", 3600), ("min", 60)):
        if segundos >= factor:
            return f"hace {int(segundos // factor)} {unidad}"
    return "hace segundos"


# --- Chequeos -----------------------------------------------------------------

def chequear_config() -> None:
    import config

    seccion("CONFIGURACIÓN")

    token = config.APIFY_TOKEN or ""
    if not token:
        add("fail", "APIFY_TOKEN", "falta: sin él no hay datos")
    elif not token.startswith("apify_api_"):
        add("warn", "APIFY_TOKEN", "no empieza por 'apify_api_' (¿cortado?)")
    else:
        add("ok", "APIFY_TOKEN", f"presente ({len(token)} chars)")

    if config.USERNAME:
        add("ok", "IG_USERNAME", "configurado (oculto en el panel)")
    else:
        add("warn", "IG_USERNAME", "sin configurar: sin perfil ni listas")

    mapa = config.watch_map()
    if mapa:
        add("ok", "WATCH_MAP", f"{len(mapa)} cuentas mapeadas ({', '.join(sorted(mapa))})")
    else:
        add("warn", "WATCH_MAP", "vacío: el panel buscaría los códigos como si fueran usuarios")

    add("ok" if config.LINKEDIN_PROFILE else "info", "LINKEDIN_PROFILE",
        "configurado" if config.LINKEDIN_PROFILE else "sin configurar (ranking de compartidos parcial)")

    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        add("ok", "Alertas Telegram", "configuradas")
    else:
        add("info", "Alertas Telegram", "sin configurar (no habrá avisos)")

    if config.DATABASE_URL:
        add("ok", "Base de datos", "Turso (nube)")
    else:
        add("info", "Base de datos", "SQLite local (no compartida con la nube)")

    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    add("ok" if sys.version_info >= (3, 9) else "fail", "Python", py)

    # Dependencias: el panel necesita unas; la línea de comandos, otras
    faltan_panel = [m for m in ("streamlit", "plotly", "openpyxl") if not _importable(m)]
    if faltan_panel:
        add("info", "Dependencias del panel",
            f"faltan: {', '.join(faltan_panel)} (solo hacen falta para `streamlit run app.py`)")
    else:
        add("ok", "Dependencias del panel", "streamlit, plotly, openpyxl")
    if config.DATABASE_URL and not _importable("libsql"):
        add("fail", "libsql", "usas Turso pero falta `pip install libsql`")
    elif config.DATABASE_URL:
        add("ok", "libsql", "necesario para Turso")


def _importable(modulo: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(modulo) is not None
    except (ImportError, ValueError):
        return False


def chequear_apify(offline: bool) -> None:
    import config

    seccion("APIFY (validez del token)")
    if offline:
        add("info", "Comprobación de red", "omitida (--no-network)")
        return
    if not config.APIFY_TOKEN:
        add("fail", "Token", "no hay token que probar")
        return
    try:
        req = urllib.request.Request(
            "https://api.apify.com/v2/users/me",
            headers={"Authorization": f"Bearer {config.APIFY_TOKEN}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode()).get("data", {})
        plan = (data.get("plan") or {}).get("id") or "?"
        add("ok", "Token válido", f"plan {plan} · usuario {data.get('username', '?')}")
    except Exception as exc:  # noqa: BLE001
        add("fail", "Token INVÁLIDO", str(exc)[:60])


def chequear_base() -> None:
    import config
    import storage

    seccion("BASE DE DATOS")
    try:
        storage.init_db()
        diag = storage.diagnose()
        add("ok", "Escritura y lectura", str(diag.get("ok", diag))[:60])
    except Exception as exc:  # noqa: BLE001
        add("fail", "Base de datos", str(exc)[:70])
        return

    err = storage.last_db_error()
    if err:
        add("warn", "Último error de escritura", err[:60])
    else:
        add("ok", "Sin errores de escritura", "")

    # Privacidad: ningún identificador real debe quedar en la base
    try:
        nombres = list(config.watch_map().values()) + config.personal_identifiers()
        conn = storage._connect()
        tablas = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'").fetchall()]
        fugas = 0
        for t in tablas:
            for c in [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]:
                for n in nombres:
                    try:
                        fugas += conn.execute(
                            f"SELECT COUNT(*) FROM {t} WHERE instr(CAST({c} AS TEXT), ?) > 0",
                            (n,)).fetchone()[0]
                    except Exception:  # noqa: BLE001
                        continue
        storage._close(conn)
        add("ok" if fugas == 0 else "fail", "Privacidad de la base",
            "0 nombres reales" if fugas == 0 else f"{fugas} celdas con nombres reales")
    except Exception as exc:  # noqa: BLE001
        add("warn", "Privacidad de la base", f"no se pudo comprobar: {exc}"[:60])


def chequear_datos() -> None:
    import storage

    seccion("DATOS ACUMULADOS")
    try:
        filas = [
            ("Capturas de perfil", len(storage.get_profile_history()), 2),
            ("Publicaciones", len(storage.get_posts()), 1),
            ("Comentarios", len(storage.get_comments()), 1),
            ("Menciones", len(storage.get_mentions()), 1),
            ("Relaciones (seguidores/seguidos)", len(storage.get_relation_history()), 2),
            ("Historial de cambios", len(storage.get_relation_events()), 2),
            ("Perfiles enriquecidos", len(storage.get_account_profiles()), 1),
            ("Historias archivadas", len(storage.get_story_archive()), 1),
            ("Threads", len(storage.get_threads_posts()), 1),
            ("LinkedIn", len(storage.get_linkedin_activity()), 1),
        ]
    except Exception as exc:  # noqa: BLE001
        add("fail", "Lectura de datos", str(exc)[:60])
        return

    for etiqueta, n, minimo in filas:
        if n == 0:
            add("warn", etiqueta, "0 — aún sin datos")
        elif etiqueta.startswith(("Capturas", "Relaciones", "Historial")) and n < minimo:
            add("info", etiqueta, f"{n} — hacen falta ≥{minimo - n} más para tendencias")
        else:
            add("ok", etiqueta, str(n))

    # Consistencia: ¿hay filas que apunten a archivos de medios que ya no existen?
    try:
        huerfanas = [s for s in storage.get_story_archive()
                     if s.get("media_path") and not Path(s["media_path"]).exists()]
        if huerfanas:
            add("warn", "Historias huérfanas",
                f"{len(huerfanas)} filas sin archivo en disco (limpia con --fix)")
        else:
            add("ok", "Medios de historias", "todos los archivos existen")
    except Exception:  # noqa: BLE001
        pass


def chequear_frescura() -> None:
    import storage

    seccion("FRESCURA (última ingesta por fuente)")
    try:
        log = storage.get_ingest_log(200)
    except Exception as exc:  # noqa: BLE001
        add("warn", "Registro de fuentes", str(exc)[:60])
        return
    if not log:
        add("warn", "Sin ingestas registradas", "nunca se ha sincronizado")
        return
    ultimas = {}
    for i in log:
        src = i.get("source") or "?"
        if src not in ultimas:
            ultimas[src] = i.get("ts")
    for src, ts in sorted(ultimas.items()):
        texto = hace(ts)
        horas = 0
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            horas = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        except (ValueError, TypeError):
            pass
        add("ok" if horas < 26 else "warn", src, texto)

    # La sync principal (Apify) es la que debe correr a diario
    if "apify" not in ultimas:
        add("fail", "apify", "NUNCA se ha sincronizado → la rutina no está corriendo")
    elif "apify-watch" not in ultimas:
        add("info", "apify-watch", "sin datos (la rutina con --watch aún no ha corrido)")


def chequear_gasto(offline: bool) -> None:
    """Presupuesto de Apify: gasto del ciclo, desglose y proyección a 30 días."""
    import config

    seccion("PRESUPUESTO APIFY")
    if offline or not config.APIFY_TOKEN:
        add("info", "Gasto", "omitido (--no-network o sin token)")
        return

    def api(ruta):
        req = urllib.request.Request(
            f"https://api.apify.com/v2/{ruta}",
            headers={"Authorization": f"Bearer {config.APIFY_TOKEN}"})
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read().decode())

    try:
        lim = api("users/me/limits").get("data", {})
        ciclo = lim.get("monthlyUsageCycle", {})
        tope = float((lim.get("limits") or {}).get("maxMonthlyUsageUsd") or 0)
        inicio, fin = str(ciclo.get("startAt"))[:10], str(ciclo.get("endAt"))[:10]
    except Exception as exc:  # noqa: BLE001
        add("warn", "Límites de Apify", str(exc)[:60])
        return

    try:
        runs = api("actor-runs?limit=100&desc=true").get("data", {}).get("items", [])
    except Exception as exc:  # noqa: BLE001
        add("warn", "Historial de runs", str(exc)[:60])
        return

    gasto, por_actor, dias = 0.0, {}, set()
    for r in runs:
        ts = str(r.get("startedAt") or "")[:10]
        if inicio and ts and ts < inicio:
            continue
        dias.add(ts)
        usd = float(r.get("usageTotalUsd") or 0)
        gasto += usd
        a = por_actor.setdefault(r.get("actId") or "?", [0, 0.0])
        a[0] += 1
        a[1] += usd

    resta = max(0.0, tope - gasto)
    pct = (gasto / tope * 100) if tope else 0
    add("ok" if pct < 70 else ("warn" if pct < 95 else "fail"), "Gasto del ciclo",
        f"${gasto:.2f} de ${tope:.2f} ({pct:.0f}%) · queda ${resta:.2f}")
    add("info", "Ciclo", f"{inicio} → {fin}")

    if por_actor:
        peor = max(por_actor.items(), key=lambda kv: kv[1][1])
        add("info", "Actor más caro",
            f"{peor[0][:22]}… ${peor[1][1]:.2f} en {peor[1][0]} runs")

    if dias and gasto:
        proyeccion = (gasto / len(dias)) * 30
        add("ok" if proyeccion <= tope else "fail", "Proyección a 30 días",
            f"${proyeccion:.2f}/mes " +
            ("✅ cabe en el plan" if proyeccion <= tope else "❌ EXCEDE el plan $5"))
    if pct >= 95:
        add("fail", "Sin crédito",
            "usa la burner (gratis) o espera al reinicio del ciclo")


def chequear_automatizacion() -> None:
    seccion("AUTOMATIZACIÓN")
    launchd_ok = False
    # launchd: en macOS es MÁS fiable que cron (ejecuta lo perdido al despertar)
    plist = Path.home() / "Library/LaunchAgents/com.igfv.igmonitor.daily.plist"
    if plist.exists():
        try:
            r = subprocess.run(["launchctl", "list"], capture_output=True,
                               text=True, timeout=10)
            cargado = "com.igfv.igmonitor.daily" in (r.stdout or "")
            launchd_ok = cargado
            add("ok" if cargado else "warn", "launchd (recomendado)",
                "cargado ✅" if cargado else "instalado pero NO cargado")
        except (OSError, subprocess.SubprocessError):
            add("info", "launchd", "plist instalado (no se pudo consultar)")
    else:
        add("info", "launchd (recomendado)",
            "./install_launchd.sh  ← no depende de que el Mac esté despierto")

    crontab = ""
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            crontab = r.stdout
        else:
            add("info", "crontab", (r.stderr or "vacío o sin permisos").strip()[:50])
            crontab = ""
    except (OSError, subprocess.SubprocessError) as exc:
        add("info", "crontab", f"no se pudo leer: {exc}"[:50])
        crontab = ""

    tareas = [l for l in crontab.splitlines() if "ig-monitor" in l or "daily.py" in l]
    if tareas:
        for t in tareas:
            add("ok", "Rutina diaria (cron)", t.strip()[:58])
    elif launchd_ok:
        add("ok", "Rutina diaria", "activa vía launchd ✅ (no hace falta cron)")
    else:
        add("fail", "Rutina diaria", "NO programada → el historial no crecerá solo")
        add("info", "Cómo activarla", "./install_launchd.sh")

    story = [l for l in crontab.splitlines() if "story_archive" in l]
    if story:
        add("ok", "Archivador de historias", "programado")
    else:
        add("warn", "Archivador de historias",
            "no programado → las historias se pierden cada día")

    if shutil.which("python3"):
        add("ok", "python3 localizable", shutil.which("python3"))

    # ¿La rutina ha corrido ALGUNA VEZ de verdad? (el crontab puede estar
    # instalado y no ejecutarse nunca: Mac dormido o bloqueo TCC de macOS)
    log = Path(__file__).resolve().parent / "daily.log"
    if log.exists():
        cuando = datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc).isoformat()
        add("ok", "daily.log", f"existe, {hace(cuando)}")
        # El fallo clásico de macOS: la rutina se ejecuta pero NO puede leer el
        # proyecto (TCC bloquea Escritorio/Documentos/Descargas).
        try:
            contenido = log.read_text(errors="replace")
        except OSError:
            contenido = ""
        tiene_error_tcc = ("Operation not permitted" in contenido
                           or "can't open file" in contenido)
        casa = str(Path.home())
        proyecto = str(Path(__file__).resolve())
        protegido = any(proyecto.startswith(f"{casa}/{c}/")
                        for c in ("Desktop", "Documents", "Downloads"))
        if tiene_error_tcc and protegido:
            add("fail", "La rutina NO puede leer los archivos",
                "bloqueo TCC de macOS (estás en una carpeta protegida)")
            add("info", "Solución", "./move_project.sh --yes")
        elif tiene_error_tcc:
            add("info", "El log tiene un fallo TCC antiguo",
                "ya no aplica: el proyecto está fuera de carpetas protegidas")
        elif contenido.strip():
            add("ok", "Última corrida del log", "sin errores de permisos")
    else:
        add("fail", "daily.log", "NO existe → la rutina nunca se ha ejecutado")
        add("info", "Diagnóstico de cron", "./cron_test.sh")
        add("info", "Solución recomendada", "./install_launchd.sh")


def imprimir_secretos() -> None:
    """Imprime el bloque exacto para Streamlit → Settings → Secrets.

    Lee tu `.env` local y lo formatea como TOML, para no transcribir a mano
    (una errata rompe el arranque o deja nombres reales a la vista).
    """
    import config

    def esc(v) -> str:
        return str(v or "").replace("\\", "\\\\").replace('"', '\\"')

    mapa = ",".join(f"{c}:{r}" for c, r in sorted(config.watch_map().items()))
    db_url = str(getattr(config, "DATABASE_URL", "") or "")
    db_tok = str(getattr(config, "DATABASE_AUTH_TOKEN", "") or "")
    print("\n" + "═" * 66)
    print("  PEGA ESTO EN STREAMLIT → Settings → Secrets")
    print("  ⚠️  Contiene tus tokens: no compartas esta pantalla.")
    print("═" * 66 + "\n")

    lineas = [
        ("APIFY_TOKEN", config.APIFY_TOKEN),
        ("IG_USERNAME", config.USERNAME),
        ("DISPLAY_NAME", config.DISPLAY_NAME),
        ("LINKEDIN_PROFILE", config.LINKEDIN_PROFILE),
    ]
    for clave, valor in lineas:
        if valor:
            print(f'{clave} = "{esc(valor)}"')

    # ⚠️ Las credenciales de Turso viven SOLO en Streamlit: si aquí salen
    # vacías, imprimirlas BORRARÍA la conexión de la nube. Nunca se incluyen.
    if db_url and not db_url.endswith("...."):
        print(f'DATABASE_URL = "{esc(db_url)}"')
    else:
        print('# DATABASE_URL = "<NO BORRAR: cópialo de tu panel de Turso>"')
    if db_tok and not db_tok.endswith("...."):
        print(f'DATABASE_AUTH_TOKEN = "{esc(db_tok)}"')
    else:
        print('# DATABASE_AUTH_TOKEN = "<NO BORRAR: cópialo de tu panel de Turso>"')

    for clave, valor in [
        ("WATCHLIST", ",".join(config.WATCHLIST)),
        ("WATCH_MAP", mapa),
        ("SHOW_LINKS", "true" if config.SHOW_LINKS else "false"),
        ("TELEGRAM_BOT_TOKEN", config.TELEGRAM_BOT_TOKEN),
        ("TELEGRAM_CHAT_ID", config.TELEGRAM_CHAT_ID),
    ]:
        print(f'{clave} = "{esc(valor)}"')

    if not (db_url and not db_url.endswith("....")):
        print("\n" + "!" * 66)
        print("  ⚠️  NO PEGUES ESTE BLOQUE SIN ANTES AÑADIR DATABASE_URL Y")
        print("      DATABASE_AUTH_TOKEN de tu panel de Turso: si los dejas")
        print("      fuera o vacíos, el panel perderá todos los datos de la nube.")
        print("!" * 66)
    print("\n" + "═" * 66)
    print("  Después: Manage app → Reboot (los secretos se leen al arrancar).")
    print("═" * 66 + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Chequeo de salud del centro de monitoreo")
    ap.add_argument("--no-network", action="store_true", help="no llamar a Apify")
    ap.add_argument("--json", action="store_true", help="salida JSON")
    ap.add_argument("--fix", action="store_true",
                    help="limpia historias huérfanas y vuelve a sanear identificadores")
    ap.add_argument("--secrets", action="store_true",
                    help="imprime el bloque exacto para Streamlit Secrets")
    args = ap.parse_args()

    if args.secrets:
        imprimir_secretos()
        return 0

    if args.fix:
        try:
            import storage
            storage.init_db()
            borradas = 0
            for s in storage.get_story_archive():
                ruta = s.get("media_path")
                if ruta and not Path(ruta).exists():
                    conn = storage._connect()
                    conn.execute("DELETE FROM story_archive WHERE story_id = ?",
                                 (s.get("story_id"),))
                    storage._close(conn)
                    borradas += 1
            saneadas = storage.scrub_identifiers()
            print(f"\n🧹 Limpieza: {borradas} historia(s) huérfana(s) y "
                  f"{saneadas} celda(s) con identificadores.\n")
        except Exception as exc:  # noqa: BLE001
            print(f"\n⚠️ No se pudo limpiar: {exc}\n", file=sys.stderr)

    if not args.json:
        print(f"\n🩺 DIAGNÓSTICO DEL SISTEMA — Centro de monitoreo IG")
        print("═" * 62)

    for fn in (chequear_config, lambda: chequear_apify(args.no_network), chequear_base,
               chequear_datos, chequear_frescura, chequear_automatizacion,
               lambda: chequear_gasto(args.no_network)):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            add("fail", f"chequeo {getattr(fn, '__name__', '?')}", str(exc)[:70])

    fallos = sum(1 for r in resultados if r["estado"] == "fail")
    avisos = sum(1 for r in resultados if r["estado"] == "warn")
    oks = sum(1 for r in resultados if r["estado"] == "ok")

    if args.json:
        print(json.dumps({"ok": oks, "avisos": avisos, "fallos": fallos,
                          "resultados": resultados}, ensure_ascii=False, indent=1))
    else:
        print("\n" + "═" * 62)
        color = ROJO if fallos else (AMBAR if avisos else VERDE)
        print(f"  {color}RESUMEN: {oks} ✅ · {avisos} ⚠️  · {fallos} ❌{FIN}")
        if fallos:
            print("  Atiende primero los ❌: son los que impiden acumular datos.")
        elif avisos:
            print("  El sistema funciona; los ⚠️ son mejoras pendientes.")
        else:
            print("  Todo en orden. 🎉")
        print()

    return 2 if fallos else (1 if avisos else 0)


if __name__ == "__main__":
    raise SystemExit(main())

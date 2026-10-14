#!/usr/bin/env bash
# ¿cron REALMENTE ejecuta tareas en este Mac?
#
# Instala dos tareas de prueba (cada minuto), espera a ver si se ejecutan, las
# quita y te dice exactamente qué está fallando:
#
#   1) ¿cron ejecuta algo?                  → si no, cron está apagado o el Mac dormido
#   2) ¿cron puede entrar en esta carpeta?  → si no, es la protección TCC de macOS
#
#   ./cron_test.sh
#
# Tarda ~80 segundos. No deja nada instalado.

set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
BASE="/tmp/ig_cron_test"
TAG="ig-monitor-crontest"

echo "════════════════════════════════════════════════════════"
echo "  TEST DE CRON"
echo "  carpeta del proyecto: $DIR"
echo "════════════════════════════════════════════════════════"
echo

rm -f "$BASE.heartbeat" "$BASE.desktop"

# Instala las dos tareas de prueba (sin tocar la rutina real)
( crontab -l 2>/dev/null | grep -v "$TAG"
  echo "* * * * * /bin/date >> $BASE.heartbeat 2>&1 # $TAG"
  # Lo importante: LEER un archivo de la carpeta (no solo hacer `cd`).
  # macOS bloquea la lectura de ~/Desktop sin permiso, y `cd` no lo detecta.
  echo "* * * * * cd '$DIR' && /bin/cat daily.py > $BASE.desktop 2>&1 # $TAG"
) | crontab - || { echo "❌ No se pudo escribir el crontab."; exit 1; }

echo "→ Tareas de prueba instaladas. Esperando hasta 80 s a que cron las ejecute…"
for _ in $(seq 1 80); do
    if [ -f "$BASE.heartbeat" ] && [ -f "$BASE.desktop" ]; then break; fi
    sleep 1
    printf "."
done
echo; echo

# --- Veredicto ---
if [ -f "$BASE.heartbeat" ]; then
    echo "✅ cron SÍ ejecuta tareas en este Mac."
    if [ -f "$BASE.desktop" ]; then
        echo "✅ cron SÍ puede LEER archivos de la carpeta del proyecto."
        echo
        echo "   Entonces la rutina debería funcionar. Si no hay daily.log,"
        echo "   revisa que el Mac esté ENCENDIDO a la hora programada"
        echo "   (cron no ejecuta tareas perdidas si estaba dormido)."
    else
        echo "❌ cron NO puede LEER los archivos (bloqueo TCC de macOS)."
        echo
        echo "   CAUSA: macOS protege Escritorio/Documentos/Descargas (TCC)."
        echo
        echo "   DOS SOLUCIONES:"
        echo "   A) Dar permiso a cron:"
        echo "      Ajustes → Privacidad y seguridad → Acceso total al disco"
        echo "      → añadir /usr/sbin/cron"
        echo "   B) Mover el proyecto fuera de Escritorio (más fiable):"
        echo "      mv '$DIR' ~/ig-monitor"
        echo "      cd ~/ig-monitor && ./install_cron.sh"
    fi
else
    echo "❌ cron NO ejecutó NADA en 80 segundos."
    echo
    echo "   POSIBLES CAUSAS Y SOLUCIONES:"
    echo "   1) El Mac estaba dormido o en reposo  → prueba con la tapa abierta"
    echo "   2) cron deshabilitado                 → sudo launchctl load -w \\"
    echo "        /System/Library/LaunchDaemons/com.vix.cron.plist"
    echo "   3) Permisos TCC                       → ver opción A/B de arriba"
    echo "   4) Mejor alternativa                  → usar GitHub Actions"
    echo "      (corre en la nube, no depende de tu Mac)"
fi

# --- Limpieza ---
crontab -l 2>/dev/null | grep -v "$TAG" | crontab - || true
rm -f "$BASE.heartbeat" "$BASE.desktop"
echo
echo "🧹 Tareas de prueba eliminadas (tu rutina real no se ha tocado)."
echo "   Comprueba que sigue ahí:  crontab -l | grep ig-monitor"

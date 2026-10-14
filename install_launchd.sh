#!/usr/bin/env bash
# Instala la rutina diaria con launchd (el sistema nativo de macOS).
#
# ¿Por qué launchd y no cron?
#   cron NO ejecuta tareas perdidas: si el Mac estaba dormido a la hora
#   programada, ese día se salta para siempre. launchd SÍ las ejecuta en cuanto
#   el Mac despierta. Es la diferencia entre "a veces corre" y "siempre corre".
#
#   ./install_launchd.sh            # instala a las 05:00 (modo económico)
#   ./install_launchd.sh 7 30       # a las 07:30
#   ./install_launchd.sh --status   # ver si está cargado
#   ./install_launchd.sh --run-now  # ejecutarlo ya (prueba real)
#   ./install_launchd.sh --full     # modo completo (comentarios, listas, LinkedIn)
#   ./install_launchd.sh --remove   # desinstalar

set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3 || echo /usr/bin/python3)"
LABEL="com.igfv.igmonitor.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

case "${1:-}" in
    --remove)
        launchctl unload "$PLIST" 2>/dev/null || true
        rm -f "$PLIST"
        echo "✅ Rutina launchd eliminada."
        exit 0 ;;
    --status)
        if [ -f "$PLIST" ]; then
            echo "Plist instalado: $PLIST"
            launchctl list | grep -i igmonitor || echo "  (no está cargado; ejecuta sin --status)"
        else
            echo "❌ No instalado."
        fi
        exit 0 ;;
    --run-now)
        echo "→ Ejecutando la rutina AHORA (prueba real)…"
        cd "$DIR" && "$PY" daily.py --watch
        exit $? ;;
esac

HOUR="${1:-5}"
MIN="${2:-0}"
LOG="$DIR/daily.log"
ERR="$DIR/daily.err"

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>$DIR/daily.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>$HOUR</integer>
        <key>Minute</key><integer>$MIN</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG</string>
    <key>StandardErrorPath</key>
    <string>$ERR</string>
    <key>RunAtLoad</key>
    <false/>
    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>
PLIST_EOF

# Validar el plist antes de cargarlo (evita fallos silenciosos)
if ! plutil -lint "$PLIST" >/dev/null 2>&1; then
    echo "❌ El plist no es válido. No se ha cargado."
    plutil -lint "$PLIST"
    exit 1
fi

launchctl unload "$PLIST" 2>/dev/null || true
if launchctl load "$PLIST" 2>/dev/null; then
    echo "✅ Rutina diaria instalada a las $(printf '%02d:%02d' "$HOUR" "$MIN") con launchd."
else
    echo "⚠️  El plist se creó pero launchctl no lo cargó."
    echo "    Prueba a cerrar sesión y volver a entrar, o reinicia."
    exit 1
fi

echo
echo "  Archivo : $PLIST"
echo "  Log     : $LOG"
echo
echo "Ventajas frente a cron:"
echo "  · si el Mac estaba dormido, se ejecuta AL DESPERTAR"
echo "  · no depende de permisos TCC"
echo
echo "Prueba real ahora : ./install_launchd.sh --run-now"
echo "Ver estado        : ./install_launchd.sh --status"
echo "Quitar el cron    : ./install_cron.sh --remove   (evita duplicados)"

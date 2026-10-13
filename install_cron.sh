#!/usr/bin/env bash
# Instala (o quita) la rutina diaria del centro de monitoreo en cron.
#
#   ./install_cron.sh            # instala la rutina a las 05:00 (con destacadas)
#   ./install_cron.sh 9 30       # a las 09:30
#   ./install_cron.sh --remove   # la quita
#   ./install_cron.sh --test     # ejecuta la rutina ahora mismo (dry-run)
#
# La rutina incluye --watch: sincroniza también los posts y comentarios de las
# cuentas destacadas.
#
# ⚠️ macOS: cron NO corre si el Mac está dormido. Despiértalo antes con:
#      sudo pmset repeat wakeorpoweron MTWRFSU 04:55:00
#    Si el proyecto está en ~/Desktop, ~/Documents o ~/Downloads, cron puede no
#    tener permiso (protección TCC): da "Full Disk Access" a /usr/sbin/cron, o
#    mueve el proyecto a una carpeta no protegida (p. ej. ~/dev/ig-monitor).

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3 || echo /usr/bin/python3)"
TAG="ig-monitor-daily"

if [ "${1:-}" = "--remove" ]; then
  crontab -l 2>/dev/null | grep -v "$TAG" | crontab - || true
  echo "✅ Rutina diaria eliminada."
  exit 0
fi

if [ "${1:-}" = "--test" ]; then
  echo "→ Ejecutando la rutina en modo prueba (no envía nada)…"
  cd "$DIR" && "$PY" daily.py --dry-run --no-sync
  exit 0
fi

HOUR="${1:-5}"
MIN="${2:-0}"
LINE="$MIN $HOUR * * * cd $DIR && $PY daily.py --watch >> $DIR/daily.log 2>&1 # $TAG"

# Quita cualquier entrada previa y añade la nueva
( crontab -l 2>/dev/null | grep -v "$TAG" || true; echo "$LINE" ) | crontab -

echo "✅ Rutina diaria instalada:"
echo "   $LINE"
echo
echo "Comprueba con:  crontab -l | grep $TAG"
echo "Prueba ahora:   ./install_cron.sh --test"
echo "Ver el log:     tail -f $DIR/daily.log"

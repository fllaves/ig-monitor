#!/usr/bin/env bash
# Mueve el proyecto fuera de ~/Desktop.
#
# POR QUÉ: macOS protege Escritorio/Documentos/Descargas (TCC). `cron` puede
# entrar (`cd`) pero NO puede LEER los archivos, así que la rutina falla con
# "Operation not permitted" y sin crear nada. Sacarlo de esas carpetas lo arregla
# de raíz, sin tocar permisos del sistema.
#
#   ./move_project.sh              # mueve a ~/ig-monitor
#   ./move_project.sh ~/dev/ig-monitor
#
# Streamlit Cloud NO se ve afectado: lee del repositorio de GitHub, no de tu Mac.

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

# Requiere confirmación explícita: mover el proyecto es una operación seria.
DEST="$HOME/ig-monitor"
CONFIRM=""
for arg in "$@"; do
    case "$arg" in
        --yes|-y) CONFIRM=1 ;;
        *) DEST="$arg" ;;
    esac
done

if [ -z "$CONFIRM" ]; then
    cat <<EOF

⚠️  Esto va a MOVER el proyecto de sitio:

      desde: $DIR
      hacia: $DEST

    Si estás seguro, ejecútalo así:

      ./move_project.sh --yes

    (Streamlit Cloud no se ve afectado: lee de GitHub, no de tu Mac.)
EOF
    exit 1
fi

if [ "$DIR" = "$DEST" ]; then
    echo "✅ Ya estás en $DEST (fuera de las carpetas protegidas)."
    exit 0
fi

case "$DIR" in
    "$HOME"/Desktop/*|"$HOME"/Documents/*|"$HOME"/Downloads/*) ;;
    *) echo "✅ $DIR no está en una carpeta protegida. No hace falta moverlo."; exit 0 ;;
esac

if [ -e "$DEST" ]; then
    echo "❌ $DEST ya existe. Elige otra ruta o bórralo."
    exit 1
fi

echo "Moviendo:  $DIR"
echo "       →   $DEST"
echo
mv "$DIR" "$DEST"
cd "$DEST"

echo "Reinstalando la rutina con las rutas nuevas…"
./install_launchd.sh 2>/dev/null || true
if ! ./install_launchd.sh --status 2>/dev/null | grep -q "no está cargado"; then
    ./install_cron.sh --remove 2>/dev/null || true
fi

echo
echo "✅ Listo. El proyecto está ahora en:"
echo "   $DEST"
echo
echo "Úsalo así a partir de ahora:"
echo "   cd $DEST"
echo "   python3 doctor.py"
echo "   python3 daily.py"
echo
echo "Comprueba que la rutina puede leer los archivos:"
echo "   ./cron_test.sh"

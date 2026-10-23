#!/usr/bin/env bash
# Pone el repositorio de GitHub en PRIVADO.
#
# ⚠️  ANTES de ejecutarlo, haz el Paso 1 (una sola vez, en el navegador):
#     Streamlit Cloud → tu usuario (arriba izq.) → Settings → Linked accounts
#     → Source control → "Connect here" → "Authorize streamlit"
#
#     Si no lo haces primero, los `git push` dejarán de desplegar y un Reboot
#     fallará. La app antigua sigue viva (cacheada), pero se queda congelada.
#
# Uso:
#   ./make_private.sh              # pide confirmación
#   ./make_private.sh --check      # solo dice si está privado o público
#   ./make_private.sh --yes        # sin preguntar

set -u

REPO="fllaves/ig-monitor"
MODO="${1:-pedir}"

api() {
    local metodo="$1" ruta="$2" datos="${3:-}"
    local token
    token=$(printf "protocol=https\nhost=github.com\n\n" \
            | git credential-osxkeychain get 2>/dev/null \
            | sed -n 's/^password=//p')
    if [ -z "$token" ]; then
        echo "❌ No encontré el token de GitHub en el Keychain."
        echo "   Comprueba que puedes hacer: git push"
        return 1
    fi
    if [ -n "$datos" ]; then
        curl -sS -X "$metodo" \
             -H "Authorization: Bearer $token" \
             -H "Accept: application/vnd.github+json" \
             -H "X-GitHub-Api-Version: 2022-11-28" \
             -d "$datos" "https://api.github.com/$ruta"
    else
        curl -sS -X "$metodo" \
             -H "Authorization: Bearer $token" \
             -H "Accept: application/vnd.github+json" \
             -H "X-GitHub-Api-Version: 2022-11-28" \
             "https://api.github.com/$ruta"
    fi
}

estado_actual() {
    api GET "repos/$REPO" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('ERROR'); raise SystemExit
if 'private' in d:
    print('privado' if d['private'] else 'publico')
else:
    print('ERROR:', d.get('message', 'sin acceso'))
"
}

echo "════════════════════════════════════════════════════════"
echo "  REPO: $REPO"
echo "════════════════════════════════════════════════════════"
echo

ACTUAL=$(estado_actual)
case "$ACTUAL" in
    privado) echo "✅ Ya está PRIVADO. No hay nada que hacer."; exit 0 ;;
    publico) echo "🔓 Ahora mismo está PÚBLICO." ;;
    *)       echo "❌ No pude consultar el repo: $ACTUAL"
             echo "   ¿El token tiene permisos de administración?"
             exit 1 ;;
esac

if [ "$MODO" = "--check" ]; then
    exit 0
fi

if [ "$MODO" != "--yes" ]; then
    echo
    echo "⚠️  ANTES de continuar, confirma que YA hiciste en Streamlit:"
    echo "    Settings → Linked accounts → Source control → 'Connect here'"
    echo "    → 'Authorize streamlit'  (permiso de repos PRIVADOS)"
    echo
    printf "¿Ya lo hiciste? [s/N] "
    read -r resp
    case "$resp" in
        s|S|si|Sí|y|Y) ;;
        *) echo "Cancelado. Haz primero el Paso 1 en Streamlit."; exit 1 ;;
    esac
fi

echo
echo "→ Poniendo el repo en privado…"
RESULTADO=$(api PATCH "repos/$REPO" '{"private": true}')

echo "$RESULTADO" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('❌ Respuesta inesperada'); raise SystemExit(1)
if d.get('private') is True:
    print('✅ El repo ahora es PRIVADO:', d.get('full_name'))
elif 'message' in d:
    print('❌ GitHub rechazó el cambio:', d['message'])
    print('   Suele ser falta de permisos en el token (necesita scope \"repo\").')
    raise SystemExit(1)
else:
    print('⚠️ Respuesta:', json.dumps(d)[:200])
    raise SystemExit(1)
"

echo
echo "Siguientes pasos:"
echo "  1. Streamlit → Manage app → Reboot   (debe arrancar igual)"
echo "  2. Comprueba que un push despliega:  git commit --allow-empty -m test && git push"

#!/usr/bin/env bash
# Panel de control de Instagram — lanzador de un clic.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "→ Creando entorno virtual (primera vez)..."
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt
fi

echo "→ Abriendo el panel en http://localhost:8501"
.venv/bin/python -m streamlit run app.py

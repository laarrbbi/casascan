#!/usr/bin/env sh
# Lanza CasaScan: prepara el entorno la primera vez, busca y abre el informe.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
[ -f config.yaml ] || .venv/bin/python -m casascan init
.venv/bin/python -m casascan buscar --abrir "$@"

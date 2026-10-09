#!/usr/bin/env sh
# Abre la plataforma CasaScan en el navegador (http://127.0.0.1:8000).
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m casascan web "$@"

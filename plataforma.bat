@echo off
rem Abre la plataforma CasaScan en el navegador (http://127.0.0.1:8000).
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
)
.venv\Scripts\python -m pip install -q -r requirements.txt
.venv\Scripts\python -m casascan web %*
pause

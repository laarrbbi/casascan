@echo off
rem Lanza CasaScan: prepara el entorno la primera vez, busca y abre el informe.
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
if not exist config.yaml .venv\Scripts\python -m casascan init
.venv\Scripts\python -m casascan buscar --abrir %*
pause

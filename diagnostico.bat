@echo off
rem Prueba cada web y guarda lo que devuelve (para arreglar lo que falle).
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python -m casascan diagnostico %*
explorer resultados
pause

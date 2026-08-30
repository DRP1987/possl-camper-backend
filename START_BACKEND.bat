@echo off
cd /d "%~dp0"
title PÖSSL Telematics Backend V1.4

if not exist .env (
  echo.
  echo ERROR: .env is missing.
  echo Copy .env.example to .env and add your settings first.
  echo.
  pause
  exit /b 1
)

if not exist .venv (
  echo Creating Python virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate

echo Checking/updating required packages...
python -m pip install --disable-pip-version-check -q -r requirements.txt

echo.
echo Starting backend on http://localhost:8787
echo API documentation: http://localhost:8787/docs
echo.
start "" "http://localhost:8787/docs"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8787
pause

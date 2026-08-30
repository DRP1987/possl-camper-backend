@echo off
cd /d "%~dp0"
title PÖSSL Backend - Windows Certificate Fix

if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate

echo.
echo Installing/updating Windows certificate trust support...
python -m pip install --upgrade pip
pip install --upgrade pip-system-certs certifi requests

echo.
echo Testing Python HTTPS access to Twilio...
python -c "import requests; r=requests.get('https://api.twilio.com',timeout=15); print('Twilio HTTPS status:',r.status_code)"

echo.
echo If the command above printed an HTTP status instead of an SSL error,
echo certificate validation is working.
pause

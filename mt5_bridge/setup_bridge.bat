@echo off
setlocal
cd /d "%~dp0"
title ManiQuantAI MT5 Bridge Setup

echo ===============================================
echo     ManiQuantAI MT5 Bridge Setup
 echo ===============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python is not installed or not on PATH.
  echo Install Python 3.11+ with "Add Python to PATH" enabled.
  pause
  exit /b 1
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Dependency installation failed.
  pause
  exit /b 1
)

if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  echo.
  echo Created .env from .env.example.
  echo Open mt5_bridge\.env and fill in:
  echo   MANIQUANT_API_URL
  echo   MT5_BRIDGE_TOKEN
) else (
  echo .env already exists; leaving it unchanged.
)

echo.
echo Setup complete.
echo Next: connect MT5 in ManiQuantAI, copy the bridge token into .env,
echo then double-click START_MT5_BRIDGE.bat.
pause

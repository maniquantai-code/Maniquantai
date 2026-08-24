@echo off
setlocal
cd /d "%~dp0"
title ManiQuantAI MT5 Bridge

echo ===============================================
echo       ManiQuantAI MetaTrader 5 Bridge
echo ===============================================
echo.

echo Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python is not installed or not on PATH.
  echo Install Python 3.11+ and enable "Add Python to PATH".
  pause
  exit /b 1
)

if not exist ".env" (
  echo ERROR: mt5_bridge\.env was not found.
  echo Copy .env.example to .env and set MANIQUANT_API_URL and MT5_BRIDGE_TOKEN.
  pause
  exit /b 1
)

echo Installing/checking bridge dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Could not install bridge dependencies.
  pause
  exit /b 1
)

echo.
echo Starting ManiQuantAI MT5 bridge...
echo Keep this window open while live trading is enabled.
echo.
python agent.py

echo.
echo The MT5 bridge stopped.
pause

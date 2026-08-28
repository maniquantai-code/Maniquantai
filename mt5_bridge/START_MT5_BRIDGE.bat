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

echo Installing/checking bridge dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: Could not install bridge dependencies.
  pause
  exit /b 1
)

echo.
echo Starting ManiQuantAI MT5 Bridge login...
echo Paste the token generated in ManiQuantAI Settings.
echo.
python bridge_app.py

if errorlevel 1 (
  echo.
  echo The MT5 bridge stopped with an error.
  pause
)

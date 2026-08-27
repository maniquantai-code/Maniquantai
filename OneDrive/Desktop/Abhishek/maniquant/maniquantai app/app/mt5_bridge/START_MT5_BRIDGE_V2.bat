@echo off
title ManiQuantAI MT5 Bridge v2
echo =============================================
echo   ManiQuantAI MT5 Bridge v2 — Agent Team
echo =============================================
echo.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)
pip install MetaTrader5 requests --quiet
echo.
echo Starting GUI...
python bridge_app.py
if errorlevel 1 (
    echo.
    echo Bridge exited with error. Check the log above.
    pause
)

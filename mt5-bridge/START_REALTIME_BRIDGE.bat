@echo off
setlocal
cd /d %~dp0

echo ================================================
echo   ManiQuantAI Realtime MT5 Bridge v2
 echo ================================================
if not exist .venv\Scripts\python.exe (
  echo Creating Python environment...
  py -3 -m venv .venv
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo Failed to install bridge dependencies.
  pause
  exit /b 1
)

echo.
echo Required environment variables:
echo   MANIQUANT_API=https://your-api-host
 echo   MT5_BRIDGE_TOKEN=your-bridge-token
 echo Optional:
echo   MT5_LOGIN / MT5_PASSWORD / MT5_SERVER
 echo   MT5_BRIDGE_SCAN_SECONDS=0.5
 echo.
.venv\Scripts\python.exe realtime_agent.py
pause

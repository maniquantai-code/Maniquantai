@echo off
setlocal
cd /d %~dp0

echo ================================================
echo   ManiQuantAI Realtime MT5 Bridge v2.1
echo ================================================

if not exist .venv\Scripts\python.exe (
  echo Creating Python environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Could not create Python environment. Install Python 3.11+ first.
    pause
    exit /b 1
  )
)

.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Failed to install bridge dependencies.
  pause
  exit /b 1
)

echo.
echo Configure these environment variables before starting:
echo   MANIQUANT_API=https://your-maniquantai-api
echo   MT5_BRIDGE_TOKEN=your-bridge-token
echo Optional account login: MT5_LOGIN / MT5_PASSWORD / MT5_SERVER
echo Optional tuning: MT5_BRIDGE_SCAN_SECONDS, MT5_BRIDGE_HEARTBEAT_SECONDS
echo Optional risk guard: MT5_MAX_SPREAD_POINTS
 echo.

if "%MANIQUANT_API%"=="" (
  echo WARNING: MANIQUANT_API is not set in this terminal.
)
if "%MT5_BRIDGE_TOKEN%"=="" (
  echo WARNING: MT5_BRIDGE_TOKEN is not set in this terminal.
)

if "%MANIQUANT_API%"=="" goto :config_error
if "%MT5_BRIDGE_TOKEN%"=="" goto :config_error

echo Starting realtime bridge...
.venv\Scripts\python.exe realtime_agent.py
if errorlevel 1 (
  echo Bridge stopped with an error.
  pause
  exit /b 1
)
exit /b 0

:config_error
echo.
echo Bridge startup cancelled: configure MANIQUANT_API and MT5_BRIDGE_TOKEN first.
pause
exit /b 2

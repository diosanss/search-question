@echo off
setlocal
cd /d "%~dp0"

set "PY="
py -3.12 --version >nul 2>nul
if not errorlevel 1 set "PY=py -3.12"
if not defined PY (
  py -3 --version >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  python --version >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo.
  echo Python 3.12+ was not found.
  echo Install it from https://www.python.org/downloads/windows/
  echo During installation, check "Add Python to PATH".
  echo.
  start "" https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo Done. Double-click run.bat to start.
pause
exit /b 0

:fail
echo.
echo Installation failed. Check your network / Python version.
echo If you are in China, try setting a mirror first:
echo   set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
pause
exit /b 1

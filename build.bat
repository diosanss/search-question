@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\pyinstaller.exe" (
  ".venv\Scripts\python.exe" -m pip install pyinstaller
  if errorlevel 1 goto :fail
)
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --name ScreenAnswer ^
  --icon "assets\icon.ico" ^
  --add-data "assets;assets" ^
  --collect-submodules winrt --collect-binaries winrt --collect-data winrt ^
  "app.py"
if errorlevel 1 goto :fail
copy /Y "README.md" "dist\ScreenAnswer\README.md" >nul
copy /Y "LICENSE" "dist\ScreenAnswer\LICENSE" >nul
copy /Y "CHANGELOG.md" "dist\ScreenAnswer\CHANGELOG.md" >nul
copy /Y "config.example.json" "dist\ScreenAnswer\config.example.json" >nul
if exist "docs" xcopy /E /I /Y "docs" "dist\ScreenAnswer\docs" >nul
if exist "ScreenAnswer-win64.zip" del /Q "ScreenAnswer-win64.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\ScreenAnswer' -DestinationPath 'ScreenAnswer-win64.zip' -Force"
if errorlevel 1 goto :fail
echo.
echo Built: dist\ScreenAnswer\ScreenAnswer.exe
echo Zip:   ScreenAnswer-win64.zip
pause
exit /b 0

:fail
echo Build failed.
pause
exit /b 1

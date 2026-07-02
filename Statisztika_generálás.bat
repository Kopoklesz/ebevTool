@echo off
chcp 65001 >nul
if "%~1"=="" (
  echo Huzd ra az Excel fajlt erre a .bat fajlra!
  pause
  exit /b
)
"%~dp0Statisztika_generalas.exe" "%~1"
pause

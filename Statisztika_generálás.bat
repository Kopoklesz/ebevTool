@echo off
chcp 65001 >nul
rem Az alkalmazas inditasa, opcionalisan a rahuzott Excel fajllal.
rem
rem FONTOS: ebben a fajlban nincs ekezet. A cmd a batch sorait a rendszer
rem kodlapjan olvassa be, ezert az UTF-8 ekezetek osszetorhetnek, es a
rem tordelt reszek parancskent futnanak le ("... is not recognized").
rem
rem Ha az .exe hianyzik, a Windows a fajlnevet mashogy probalna ertelmezni, es
rem felrevezeto hibat adna (pl. "nincs Python a gepen"). Ezert itt elore
rem ellenorizzuk, es ertheto uzenetet irunk ki.

set "APP=%~dp0Statisztika_generalas.exe"

if not exist "%APP%" (
    echo.
    echo  HIBA: Nem talalhato az alkalmazas.
    echo.
    echo  Hianyzo fajl:
    echo    %APP%
    echo.
    echo  A "Statisztika_generalas.exe" fajlnak ugyanabban a mappaban kell
    echo  lennie, mint ennek a .bat fajlnak.
    echo.
    echo  Ha most frissitetted a programot, lehet, hogy a csere nem fejezodott
    echo  be. Ilyenkor toltsd le ujra a legfrissebb kiadast a GitHubrol.
    echo.
    pause
    exit /b 1
)

start "" "%APP%" %1

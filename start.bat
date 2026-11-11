@echo off
title Snipe Token Bot
color 0B

:banner
echo.
echo  =====================================================
echo    SNIPE TOKEN BOT - Smart Money Tracker
echo    56+ Blockchains . GoPlus Security . CSV Export
echo  =====================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python non installe. Lance install.bat d'abord.
    pause
    exit /b 1
)

:: Check .env
if not exist ".env" (
    echo [ERREUR] Fichier .env manquant. Lance install.bat d'abord.
    pause
    exit /b 1
)

echo  Demarrage en cours...
echo  Pour arreter definitivement: Ctrl+C puis O
echo.

:start
python start.py
set EXIT_CODE=%ERRORLEVEL%

:: Exit code 0 = propre (KeyboardInterrupt ou SystemExit(0))
if %EXIT_CODE% EQU 0 (
    echo.
    echo  Bot arrete proprement.
    goto end
)

:: Exit code 1 = crash
echo.
echo  [!] Le bot a plante (code %EXIT_CODE%).
echo  [!] Redemarrage automatique dans 10 secondes...
echo  [!] Appuie sur Ctrl+C pour annuler.
echo.
timeout /t 10 /nobreak >nul
if errorlevel 1 goto end
goto start

:end
echo.
pause

@echo off
title Snipe Token Bot
echo.
echo  ============================================
echo    SNIPE TOKEN BOT - Demarrage
echo  ============================================
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

echo Demarrage en cours...
echo Pour arreter le bot: Ctrl+C
echo.
python start.py

echo.
echo Bot arrete.
pause

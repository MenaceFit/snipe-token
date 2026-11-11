@echo off
title Snipe Token Bot - Installation
echo.
echo  ============================================
echo    SNIPE TOKEN BOT - Installation Windows
echo  ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python non installe !
    echo.
    echo  Installe Python 3.11+ depuis:
    echo  https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: Coche "Add Python to PATH" pendant l'installation !
    pause
    exit /b 1
)

echo [OK] Python detecte
python --version

echo.
echo [1/3] Mise a jour de pip...
python -m pip install --upgrade pip --quiet

echo [2/3] Installation des dependances...
python -m pip install -r requirements.txt

echo [3/3] Configuration initiale...
if not exist ".env" (
    copy ".env.example" ".env"
    echo.
    echo  [IMPORTANT] Le fichier .env a ete cree.
    echo  Ouvre-le avec Notepad et remplis au minimum:
    echo    - TELEGRAM_BOT_TOKEN
    echo    - TELEGRAM_CHAT_IDS
    echo.
    echo  Pour obtenir un token: Telegram ^> @BotFather ^> /newbot
    echo  Pour obtenir ton Chat ID: Telegram ^> @userinfobot
)

echo.
echo  ============================================
echo    Installation terminee !
echo.
echo    Lance le bot avec:  start.bat
echo    Ou directement:     python start.py
echo  ============================================
echo.
pause

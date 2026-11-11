@echo off
title Snipe Token Bot - Build EXE
echo.
echo  ============================================
echo    BUILD EXE - PyInstaller
echo  ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python requis. Lance install.bat d'abord.
    pause
    exit /b 1
)

echo Installation de PyInstaller...
python -m pip install pyinstaller --quiet

echo.
echo Construction de l'executable...
echo (Cela peut prendre 2-5 minutes)
echo.

pyinstaller ^
    --onefile ^
    --name "SnipeTokenBot" ^
    --icon NONE ^
    --add-data "config;config" ^
    --add-data ".env.example;." ^
    --hidden-import "aiosqlite" ^
    --hidden-import "fakeredis" ^
    --hidden-import "fakeredis.aioredis" ^
    --hidden-import "sqlalchemy.dialects.sqlite" ^
    --hidden-import "telegram" ^
    --hidden-import "telegram.ext" ^
    --collect-all "telegram" ^
    --collect-all "aiohttp" ^
    --noconfirm ^
    start.py

if errorlevel 1 (
    echo.
    echo [ERREUR] Build echoue.
    pause
    exit /b 1
)

echo.
echo  ============================================
echo    EXE cree dans: dist\SnipeTokenBot.exe
echo.
echo    Pour l'utiliser:
echo    1. Copie .env dans le meme dossier que l'exe
echo    2. Double-clique sur SnipeTokenBot.exe
echo  ============================================
echo.
pause

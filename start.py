#!/usr/bin/env python3
"""
Snipe Token Bot — Windows-friendly launcher.
Checks dependencies, sets up the database, then starts the bot.
"""
import asyncio
import os
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent


def check_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        example = ROOT / ".env.example"
        if example.exists():
            import shutil
            shutil.copy(example, env_file)
            print("✅ .env créé depuis .env.example")
            print("⚠️  IMPORTANT: Ouvre .env et remplis TELEGRAM_BOT_TOKEN !")
            print(f"   Fichier: {env_file}")
            input("Appuie sur Entrée après avoir configuré .env...")
        else:
            print("❌ Fichier .env manquant. Crée-le avec tes tokens Telegram.")
            sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv(env_file)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token or token == "your_telegram_bot_token_here":
        print("❌ TELEGRAM_BOT_TOKEN non configuré dans .env")
        print("   1. Ouvre .env dans un éditeur de texte")
        print("   2. Remplace 'your_telegram_bot_token_here' par ton vrai token")
        print("   3. Obtiens un token sur Telegram via @BotFather → /newbot")
        input("Appuie sur Entrée pour quitter...")
        sys.exit(1)


def check_deps():
    missing = []
    for pkg in ["telegram", "aiohttp", "sqlalchemy", "fakeredis", "aiosqlite"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"⚠️  Packages manquants: {', '.join(missing)}")
        print("📦 Installation en cours...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
        print("✅ Installation terminée !")


async def run_migrations():
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "alembic", "upgrade", "head",
            cwd=str(ROOT),
        )
        await proc.wait()
    except Exception as e:
        print(f"⚠️  Migration: {e} (continuing anyway)")


async def main():
    print("=" * 50)
    print("  🎯 SNIPE TOKEN BOT")
    print("  Détection Smart Money · 56 blockchains")
    print("=" * 50)
    print()

    check_env()
    check_deps()

    print("🗄️  Initialisation base de données SQLite...")
    await run_migrations()

    print("🚀 Démarrage du bot...")
    print()

    from main import main as bot_main
    await bot_main()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot arrêté.")

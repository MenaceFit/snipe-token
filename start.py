#!/usr/bin/env python3
"""
Snipe Token Bot — Windows-friendly launcher.
Rich colored output + auto-restart on crash (up to 10 times).
"""
import asyncio
import os
import sys
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).parent
MAX_RESTARTS = 10
RESTART_BACKOFF = [5, 10, 20, 30, 60, 60, 120, 120, 300, 300]

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    console = Console()
    RICH = True
except ImportError:
    RICH = False


def _print(msg: str, style: str = "") -> None:
    if RICH:
        console.print(msg, style=style)
    else:
        print(msg)


def _banner() -> None:
    if RICH:
        banner = Text()
        banner.append("  🎯 SNIPE TOKEN BOT\n", style="bold cyan")
        banner.append("  Smart Money Tracker · 56+ Blockchains\n", style="dim")
        banner.append("  GoPlus Security · CSV Export · Watchlist", style="dim")
        console.print(Panel(banner, border_style="cyan", padding=(0, 2)))
    else:
        print("=" * 55)
        print("  🎯 SNIPE TOKEN BOT")
        print("  Smart Money Tracker · 56+ Blockchains")
        print("=" * 55)
    print()


def check_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        example = ROOT / ".env.example"
        if example.exists():
            import shutil
            shutil.copy(example, env_file)
            _print("✅ .env créé depuis .env.example", "green")
            _print("⚠️  IMPORTANT: Ouvre .env et remplis TELEGRAM_BOT_TOKEN !", "yellow bold")
            _print(f"   Fichier: {env_file}", "dim")
            input("Appuie sur Entrée après avoir configuré .env...")
        else:
            _print("❌ Fichier .env manquant.", "red bold")
            sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv(env_file)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token or token == "your_telegram_bot_token_here":
        _print("❌ TELEGRAM_BOT_TOKEN non configuré dans .env", "red bold")
        _print("   1. Ouvre .env dans un éditeur de texte", "dim")
        _print("   2. Remplace la valeur par ton vrai token", "dim")
        _print("   3. Obtiens un token sur Telegram via @BotFather → /newbot", "dim")
        input("Appuie sur Entrée pour quitter...")
        sys.exit(1)


def check_deps() -> None:
    """Check all critical packages; install from requirements.txt if any are missing."""
    CRITICAL = [
        ("telegram",          "python-telegram-bot"),
        ("aiohttp",           "aiohttp"),
        ("sqlalchemy",        "SQLAlchemy"),
        ("fakeredis",         "fakeredis"),
        ("aiosqlite",         "aiosqlite"),
        ("rich",              "rich"),
        ("pydantic_settings", "pydantic-settings"),
        ("dotenv",            "python-dotenv"),
        ("uvicorn",           "uvicorn"),
        ("redis",             "redis"),
        ("alembic",           "alembic"),
    ]
    missing = [name for pkg, name in CRITICAL if not _can_import(pkg)]
    if missing:
        _print(f"⚠️  Packages manquants: {', '.join(missing)}", "yellow")
        _print("📦 Installation en cours (peut prendre quelques minutes)...", "cyan")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")]
            )
            _print("✅ Installation terminée !", "green")
        except subprocess.CalledProcessError as e:
            _print(f"❌ Erreur pip install: {e}", "red bold")
            _print("   Lance manuellement: pip install -r requirements.txt", "dim")
            sys.exit(1)
        import importlib
        importlib.invalidate_caches()
    else:
        _print("✅ Dépendances OK.", "dim")


def _can_import(pkg: str) -> bool:
    try:
        __import__(pkg)
        return True
    except ImportError:
        return False


async def run_migrations() -> None:
    _print("🗄️  Migrations SQLite...", "dim")
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "alembic", "upgrade", "head",
            cwd=str(ROOT),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        _print("✅ Base de données prête.", "green")
    except Exception as e:
        _print(f"⚠️  Migration: {e} (continuing anyway)", "yellow")


async def run_bot() -> None:
    from main import main as bot_main
    await bot_main()


async def main() -> None:
    _banner()

    check_deps()   # installe les deps AVANT check_env (qui a besoin de dotenv)
    check_env()
    await run_migrations()

    _print("🚀 Démarrage du bot...", "bold cyan")
    _print("", "")

    restart_count = 0
    while restart_count <= MAX_RESTARTS:
        start_time = time.monotonic()
        try:
            await run_bot()
            # Clean exit
            _print("\n👋 Bot arrêté proprement.", "dim")
            break
        except KeyboardInterrupt:
            _print("\n👋 Interruption clavier. Au revoir !", "yellow")
            break
        except SystemExit as e:
            if e.code == 0:
                _print("\n👋 Bot arrêté.", "dim")
            else:
                _print(f"\n❌ Exit code {e.code}.", "red")
            break
        except Exception as exc:
            uptime = time.monotonic() - start_time
            restart_count += 1
            if restart_count > MAX_RESTARTS:
                _print(f"\n💀 {MAX_RESTARTS} redémarrages atteints. Arrêt définitif.", "red bold")
                _print(f"   Dernière erreur: {exc}", "red")
                break

            delay = RESTART_BACKOFF[min(restart_count - 1, len(RESTART_BACKOFF) - 1)]
            _print(
                f"\n⚠️  Crash après {uptime:.0f}s — Erreur: {exc}",
                "yellow",
            )
            _print(
                f"🔄 Redémarrage {restart_count}/{MAX_RESTARTS} dans {delay}s...",
                "cyan",
            )
            await asyncio.sleep(delay)
            _print("🚀 Redémarrage...", "bold cyan")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot arrêté.")

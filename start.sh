#!/bin/bash
echo "============================================"
echo "  SNIPE TOKEN BOT - Démarrage"
echo "============================================"

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 non installé."
    echo "   Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "   Mac: brew install python"
    exit 1
fi

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "⚠️  .env créé. Configure TELEGRAM_BOT_TOKEN avant de continuer."
    echo "   Ouvre .env et remplis tes tokens Telegram."
    exit 1
fi

if ! python3 -c "import telegram" 2>/dev/null; then
    echo "📦 Installation des dépendances..."
    pip3 install -r requirements.txt
fi

echo "🚀 Démarrage..."
python3 start.py

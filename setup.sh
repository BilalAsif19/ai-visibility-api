#!/usr/bin/env bash
# Quick local setup without Docker — uses SQLite and simulated external data
# by default, so it runs with zero paid API dependencies.
set -e

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — add your ANTHROPIC_API_KEY (or OPENAI_API_KEY) to enable real LLM calls."
fi

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

export FLASK_APP=run.py
if [ ! -d migrations/versions ]; then
  flask db init
fi
flask db migrate -m "initial schema" || true
flask db upgrade

echo "Setup complete. Run the app with: source venv/bin/activate && flask run"

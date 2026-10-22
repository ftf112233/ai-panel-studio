#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
echo "[1/3] prepare venv"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
echo "[2/3] install deps"
pip install -r backend/requirements.txt
echo "[3/3] start server: http://127.0.0.1:8000"
cd backend
python -m uvicorn app.main:app --port 8000

#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
exec python -m uvicorn app.main:app --reload --port 8000

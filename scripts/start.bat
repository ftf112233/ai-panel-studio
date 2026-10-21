@echo off
chcp 936 >nul
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r backend\requirements.txt
cd backend
python -m uvicorn app.main:app --reload --port 8000

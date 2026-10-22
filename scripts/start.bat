@echo off
chcp 936 >nul
cd /d "%~dp0.."
echo [1/3] prepare venv
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
echo [2/3] install deps
pip install -r backend\requirements.txt
echo [3/3] start server: http://127.0.0.1:8000
cd backend
python -m uvicorn app.main:app --port 8000

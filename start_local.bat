@echo off
echo ========================================================
echo       Starting NetPulse Locally (FastAPI + React)
echo ========================================================

echo [1/3] Starting Backend Server (FastAPI on http://localhost:8000)...
start "NetPulse Backend" cmd /k "python run_backend.py"

timeout /t 2 >nul

echo [2/3] Starting Frontend Dashboard (Vite React on http://localhost:5173)...
start "NetPulse Frontend" cmd /k "cd frontend && npm run dev"

timeout /t 3 >nul

echo [3/3] Starting Local Monitoring Agent (Probing LAN, Gateway, DNS, WAN)...
start "NetPulse Agent" cmd /k "python agent\agent.py"

echo ========================================================
echo NetPulse is now running!
echo Dashboard: http://localhost:5173
echo API Docs:  http://localhost:8000/docs
echo ========================================================
pause

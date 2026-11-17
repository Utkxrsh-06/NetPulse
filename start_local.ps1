Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "      Starting NetPulse Locally (FastAPI + React)" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

Write-Host "`n[1/3] Starting Backend Server (http://localhost:8000)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python run_backend.py"

Start-Sleep -Seconds 2

Write-Host "[2/3] Starting Frontend Dashboard (http://localhost:5173)..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; npm run dev"

Start-Sleep -Seconds 3

Write-Host "[3/3] Starting Local Monitoring Agent..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python agent/agent.py"

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "NetPulse is now running!" -ForegroundColor Yellow
Write-Host "Dashboard: http://localhost:5173" -ForegroundColor Yellow
Write-Host "API Docs:  http://localhost:8000/docs" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan

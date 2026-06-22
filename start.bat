@echo off
chcp 65001 >nul 2>&1
setlocal

echo.
echo ============================================
echo   Label Fast - Starting services...
echo ============================================
echo.
echo   Backend:  http://localhost:8000
echo   API docs: http://localhost:8000/docs
echo   Frontend: http://localhost:5173
echo.
echo   Two new windows will open.
echo   Close each window to stop its service.
echo.

echo [1/2] Starting backend (conda: label_v4)...
start "LabelFast-Backend" cmd /k "call conda activate label_v4 && cd /d %~dp0backend && python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload"

echo [2/2] Starting frontend...
start "LabelFast-Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 3 /nobreak >nul

echo.
echo ============================================
echo   Both services started in new windows.
echo ============================================
echo.
echo Press any key to close this window (services will keep running)...
pause >nul

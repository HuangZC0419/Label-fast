@echo off
chcp 65001 >nul 2>&1
setlocal

rem ============================================================================
rem   数据标注与分类工具 一键启动脚本
rem   维护工具：DeepSeek Harness（国产编码助手）
rem ============================================================================
rem
rem ============================================================================
rem   Window strategy
rem   ---------------------------------------------------------------------------
rem   If Windows Terminal (wt.exe) is available, every service is opened as a
rem   tab in ONE new Terminal window (one tab per service).
rem   Closing a tab stops that service; closing the window stops all of them.
rem   When wt.exe is missing the script falls back to seven separate console
rem   windows (the classic behaviour).
rem ============================================================================
set "HAS_WT="
where wt.exe >nul 2>&1
if not errorlevel 1 set "HAS_WT=1"
rem  First tab creates the window (-1 = always a new window); the following tabs
rem  join the most recently used window (0 = current/recent window).
set "WT_WIN=-1"

echo.
echo ============================================
echo   数据标注与分类工具 - Starting services...
echo ============================================
echo.
echo   Detecting free ports...
echo.

rem ============================================================================
rem   Port probing: bind a TcpListener on 0.0.0.0 (IPAddress.Any).
rem   If the port is occupied, increment by 1 and retry (never abort).
rem ============================================================================
set "BACKEND_PORT=3002"
set "GB_BACKEND_PORT=8000"
set "MIX_BACKEND_PORT=3200"
set "MODEL_BACKEND_PORT=8267"
set "OCR_WORKER_PORT=8870"
set "MINERU_API_PORT=18000"
set "FRONTEND_PORT=5175"

rem  每次从各自的起始端口开始逐个 +1 尝试绑定，直到找到空闲端口；
rem  已分配的端口会被跳过，保证七个服务不会拿到同一个端口。
for /f "tokens=1-7" %%A in ('powershell -NoProfile -Command "$starts=@(3002,8000,3200,8267,8870,18000,5175); $used=@(); $out=@(); foreach($s in $starts){ $p=$s; while($p -lt 65535){ if($used -notcontains $p){ try { $l=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Any,$p); $l.ExclusiveAddressUse=$true; $l.Start(); $l.Stop(); $used+=$p; $out+=$p; break } catch { } } $p++ } }; if($out.Count -lt 7){ exit 1 }; Write-Output ($out -join [char]32)"') do (
  set "BACKEND_PORT=%%A"
  set "GB_BACKEND_PORT=%%B"
  set "MIX_BACKEND_PORT=%%C"
  set "MODEL_BACKEND_PORT=%%D"
  set "OCR_WORKER_PORT=%%E"
  set "MINERU_API_PORT=%%F"
  set "FRONTEND_PORT=%%G"
)

rem 仅探测端口并退出，便于自检：start.bat --check
if /i "%~1"=="--check" (
  echo BACKEND_PORT=%BACKEND_PORT%
  echo GB_BACKEND_PORT=%GB_BACKEND_PORT%
  echo MIX_BACKEND_PORT=%MIX_BACKEND_PORT%
  echo MODEL_BACKEND_PORT=%MODEL_BACKEND_PORT%
  echo OCR_WORKER_PORT=%OCR_WORKER_PORT%
  echo MINERU_API_PORT=%MINERU_API_PORT%
  echo FRONTEND_PORT=%FRONTEND_PORT%
  exit /b 0
)

echo   数据标注与分类工具 backend port: %BACKEND_PORT%
echo   GB backend port:        %GB_BACKEND_PORT%
echo   Mixed backend port:     %MIX_BACKEND_PORT%
echo   Model backend port:     %MODEL_BACKEND_PORT%
echo   OCR Worker port:        %OCR_WORKER_PORT%
echo   MinerU API port:        %MINERU_API_PORT%
echo   Frontend port:          %FRONTEND_PORT%
echo.
echo   数据标注与分类工具 API:  http://localhost:%BACKEND_PORT%
echo   GB API docs:    http://localhost:%GB_BACKEND_PORT%/docs
echo   Mixed backend:  http://localhost:%MIX_BACKEND_PORT%
echo   Model backend:  http://localhost:%MODEL_BACKEND_PORT%
echo   OCR Worker:     http://localhost:%OCR_WORKER_PORT%
echo   MinerU API:     http://localhost:%MINERU_API_PORT%
echo   Frontend:       http://localhost:%FRONTEND_PORT%
echo   Note: if a port is taken after detection, use the address printed by that service's tab/window.
echo.
if defined HAS_WT (
  echo   All services will open as tabs in one new Windows Terminal window.
  echo   Close a tab to stop that service; close the window to stop all services.
) else (
  echo   Windows Terminal was not found; seven separate console windows will open.
  echo   Close each window to stop its service.
)
echo.

rem ============================================================================
rem   Mixed annotation runtime environment.
rem   Model and OCR data are kept under mixed_annotation so they stay local.
rem ============================================================================
set "MIX_ROOT=%~dp0mixed_annotation"
set "MODELSCOPE_CACHE=%MIX_ROOT%\models\modelscope"
set "HF_HOME=%MIX_ROOT%\models\huggingface"
set "HF_HUB_CACHE=%MIX_ROOT%\models\huggingface\hub"
set "TORCH_HOME=%MIX_ROOT%\models\torch"
set "OCR_WORKER_DATA_DIR=%MIX_ROOT%\ocr_worker\data"
set "MINERU_API_OUTPUT_ROOT=%MIX_ROOT%\ocr_worker\data\mineru_api_output"
set "MINERU_MODEL_SOURCE=modelscope"
set "HF_HUB_DISABLE_SYMLINKS=1"
set "MINERU_RUNNER=%MIX_ROOT%\ocr_worker\mineru_runner.py"
set "MINERU_DEVICE_MODE=cuda"
set "OCR_ENGINE=mineru"
set "MINERU_MODE=auto"
set "OCR_WORKER_CONCURRENCY=3"
set "MINERU_BACKEND=pipeline"
set "MINERU_LANGUAGE=ch"
set "MINERU_PARSE_METHOD=auto"
set "MINERU_HIGH_ACCURACY=0"
set "MINERU_API_MAX_CONCURRENT_REQUESTS=3"
set "MINERU_API_TASK_RETENTION_SECONDS=3600"
if not exist "%OCR_WORKER_DATA_DIR%" mkdir "%OCR_WORKER_DATA_DIR%" >nul 2>&1
if not exist "%MINERU_API_OUTPUT_ROOT%" mkdir "%MINERU_API_OUTPUT_ROOT%" >nul 2>&1

echo [1/7] Starting Model Annotation backend (conda: CFwin11) on port %MODEL_BACKEND_PORT%...
rem Model backend imports torch and model data at startup and needs ~20s before it
rem starts listening, so start it first and let it warm up while other services launch.
call :launch "Model-Backend" "%~dp0model_annotation\backend" "call conda activate CFwin11 && set PYTHONNOUSERSITE=1 && python -m uvicorn main:app --host 127.0.0.1 --port %MODEL_BACKEND_PORT%" "#8B5CF6"
rem  The window now exists; every later tab joins it instead of opening a window.
set "WT_WIN=0"

echo [2/7] Starting 数据标注与分类工具 backend (conda: CFwin11) on port %BACKEND_PORT%...
call :launch "数据标注与分类工具-Backend" "%~dp0backend" "call conda activate CFwin11 && python -m uvicorn server:app --host 127.0.0.1 --port %BACKEND_PORT% --reload" "#3B82F6"

echo [3/7] Starting GB-Fenlei backend (conda: CFwin11) on port %GB_BACKEND_PORT%...
call :launch "GB-Fenlei-Backend" "%~dp0GB_fenlei\backend" "call conda activate CFwin11 && python -m uvicorn main:app --host 127.0.0.1 --port %GB_BACKEND_PORT%" "#22C55E"

echo [4/7] Starting MinerU API (conda: CFwin11) on port %MINERU_API_PORT%...
call :launch "MinerU-API" "%MIX_ROOT%\ocr_worker" "call conda activate CFwin11 && python -m mineru.cli.fast_api --host 127.0.0.1 --port %MINERU_API_PORT%" "#F59E0B"

rem Wait up to 20 seconds for the MinerU API health endpoint.
set "MINERU_HEALTH="
echo   Waiting for the MinerU API health endpoint (up to 20 seconds)...
for /f "usebackq delims=" %%h in (`powershell -NoProfile -Command "$url='http://127.0.0.1:%MINERU_API_PORT%/health'; $deadline=(Get-Date).AddSeconds(20); while((Get-Date) -lt $deadline){ try { $r=Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 300){ Write-Output 'OK'; break } } catch { }; Start-Sleep -Milliseconds 500 }"`) do set "MINERU_HEALTH=%%h"

if not defined MINERU_HEALTH (
  echo   MinerU API health check failed; falling back to subprocess mode with one OCR worker.
  set "MINERU_MODE=subprocess"
  set "OCR_WORKER_CONCURRENCY=1"
) else (
  echo   MinerU API is ready.
)

set "MINERU_API_URL=http://127.0.0.1:%MINERU_API_PORT%"
set "OCR_WORKER_URL=http://127.0.0.1:%OCR_WORKER_PORT%"

echo [5/7] Starting Mixed OCR Worker (conda: CFwin11) on port %OCR_WORKER_PORT%...
call :launch "Mixed-OCR-Worker" "%MIX_ROOT%\ocr_worker" "call conda activate CFwin11 && python -m uvicorn app:app --host 127.0.0.1 --port %OCR_WORKER_PORT%" "#EAB308"

echo [6/7] Starting Mixed backend (conda: CFwin11) on port %MIX_BACKEND_PORT%...
call :launch "Mixed-Backend" "%MIX_ROOT%\backend" "call conda activate CFwin11 && python -m uvicorn app:app --host 127.0.0.1 --port %MIX_BACKEND_PORT%" "#14B8A6"

rem ============================================================================
rem   Wait for every API the frontend proxies to before starting the frontend.
rem   Without this, the first page load fires requests while the Python apps are
rem   still importing and Vite reports ECONNREFUSED for those endpoints.
rem ============================================================================
call :wait_port %BACKEND_PORT% "数据标注与分类工具 backend"
call :wait_port %GB_BACKEND_PORT% "GB-Fenlei backend"
call :wait_port %MODEL_BACKEND_PORT% "Model Annotation backend"
call :wait_port %MIX_BACKEND_PORT% "Mixed backend"

echo [7/7] Starting frontend on port %FRONTEND_PORT%...
call :launch "数据标注与分类工具-Frontend" "%~dp0frontend" "set BACKEND_PORT=%BACKEND_PORT% && set GB_BACKEND_PORT=%GB_BACKEND_PORT% && set MIX_BACKEND_PORT=%MIX_BACKEND_PORT% && set MODEL_BACKEND_PORT=%MODEL_BACKEND_PORT% && set FRONTEND_PORT=%FRONTEND_PORT% && npm run dev -- --port %FRONTEND_PORT%" "#EC4899"

timeout /t 3 /nobreak >nul 2>&1

echo.
echo ============================================
if defined HAS_WT (
  echo   All seven services started as tabs in one Windows Terminal window.
) else (
  echo   All seven services started in separate console windows.
)
echo   数据标注与分类工具 API:  http://localhost:%BACKEND_PORT%
echo   GB API docs:    http://localhost:%GB_BACKEND_PORT%/docs
echo   Mixed backend:  http://localhost:%MIX_BACKEND_PORT%
echo   Model backend:  http://localhost:%MODEL_BACKEND_PORT%
echo   OCR Worker:     http://localhost:%OCR_WORKER_PORT%
echo   MinerU API:     http://localhost:%MINERU_API_PORT%
echo   Frontend:       http://localhost:%FRONTEND_PORT%
echo ============================================
echo.
echo Press any key to close this window (services will keep running)...
pause >nul

rem ============================================================================
rem   Manual start (equivalent to the services started above).
rem   Run each command in its own cmd window or Windows Terminal tab; closing
rem   that window/tab stops the service it runs. Ports may be changed if the
rem   defaults are occupied. [项目根目录] is the folder holding this script.
rem ============================================================================
rem
rem   [Terminal 1] MinerU API (default port 18000)
rem     call conda activate CFwin11
rem     set MODELSCOPE_CACHE=[项目根目录]\mixed_annotation\models\modelscope
rem     set HF_HOME=[项目根目录]\mixed_annotation\models\huggingface
rem     set HF_HUB_CACHE=[项目根目录]\mixed_annotation\models\huggingface\hub
rem     set TORCH_HOME=[项目根目录]\mixed_annotation\models\torch
rem     set MINERU_MODEL_SOURCE=modelscope
rem     set HF_HUB_DISABLE_SYMLINKS=1
rem     set MINERU_DEVICE_MODE=cuda
rem     set MINERU_BACKEND=pipeline
rem     set MINERU_LANGUAGE=ch
rem     set MINERU_PARSE_METHOD=auto
rem     set MINERU_HIGH_ACCURACY=0
rem     cd /d [项目根目录]\mixed_annotation\ocr_worker
rem     python -m mineru.cli.fast_api --host 127.0.0.1 --port 18000
rem
rem   [Terminal 2] Mixed OCR Worker (default port 8870)
rem     call conda activate CFwin11
rem     set MODELSCOPE_CACHE=[项目根目录]\mixed_annotation\models\modelscope
rem     set HF_HOME=[项目根目录]\mixed_annotation\models\huggingface
rem     set HF_HUB_CACHE=[项目根目录]\mixed_annotation\models\huggingface\hub
rem     set TORCH_HOME=[项目根目录]\mixed_annotation\models\torch
rem     set OCR_WORKER_DATA_DIR=[项目根目录]\mixed_annotation\ocr_worker\data
rem     set MINERU_API_OUTPUT_ROOT=[项目根目录]\mixed_annotation\ocr_worker\data\mineru_api_output
rem     set MINERU_MODEL_SOURCE=modelscope
rem     set HF_HUB_DISABLE_SYMLINKS=1
rem     set MINERU_RUNNER=[项目根目录]\mixed_annotation\ocr_worker\mineru_runner.py
rem     set MINERU_DEVICE_MODE=cuda
rem     set OCR_ENGINE=mineru
rem     set MINERU_MODE=auto
rem     set OCR_WORKER_CONCURRENCY=3
rem     set MINERU_BACKEND=pipeline
rem     set MINERU_LANGUAGE=ch
rem     set MINERU_PARSE_METHOD=auto
rem     set MINERU_HIGH_ACCURACY=0
rem     set MINERU_API_MAX_CONCURRENT_REQUESTS=3
rem     set MINERU_API_TASK_RETENTION_SECONDS=3600
rem     set MINERU_API_URL=http://127.0.0.1:18000
rem     set OCR_WORKER_URL=http://127.0.0.1:8870
rem     cd /d [项目根目录]\mixed_annotation\ocr_worker
rem     python -m uvicorn app:app --host 127.0.0.1 --port 8870
rem
rem   [Terminal 3] Mixed backend (default port 3200)
rem     call conda activate CFwin11
rem     set MINERU_API_URL=http://127.0.0.1:18000
rem     set OCR_WORKER_URL=http://127.0.0.1:8870
rem     cd /d [项目根目录]\mixed_annotation\backend
rem     python -m uvicorn app:app --host 127.0.0.1 --port 3200
rem
rem   [Terminal 4] Model Annotation backend (default port 8267)
rem     call conda activate CFwin11
rem     set PYTHONNOUSERSITE=1
rem     cd /d [项目根目录]\model_annotation\backend
rem     python -m uvicorn main:app --host 127.0.0.1 --port 8267
rem
rem   [Terminal 5] 数据标注与分类工具 backend (default port 3002)
rem     call conda activate CFwin11
rem     cd /d [项目根目录]\backend
rem     python -m uvicorn server:app --host 127.0.0.1 --port 3002 --reload
rem
rem   [Terminal 6] GB-Fenlei backend (default port 8000)
rem     call conda activate CFwin11
rem     cd /d [项目根目录]\GB_fenlei\backend
rem     python -m uvicorn main:app --host 127.0.0.1 --port 8000
rem
rem   [Terminal 7] Frontend (default port 5175)
rem     set BACKEND_PORT=3002
rem     set GB_BACKEND_PORT=8000
rem     set MIX_BACKEND_PORT=3200
rem     set MODEL_BACKEND_PORT=8267
rem     set FRONTEND_PORT=5175
rem     cd /d [项目根目录]\frontend
rem     npm run dev -- --port 5175
rem
rem   Open http://localhost:5175 in the browser. The frontend proxies /api and
rem   /minimind to the 数据标注与分类工具 backend, /gb-api to the GB backend,
rem   /mix-api to the mixed annotation backend, and /model-api to the model
rem   annotation backend.
rem ============================================================================

goto :eof

rem ============================================================================
rem   Subroutines
rem ============================================================================

:launch
rem  Start one service in its own console host.
rem  %1 = tab/window title   %2 = working directory
rem  %3 = command executed by cmd /k   %4 = tab colour (#RRGGBB)
rem
rem  With Windows Terminal the command becomes a tab in the current window;
rem  without it the classic separate console window is used.
rem  No setlocal here: clearing HAS_WT on failure must reach the caller.
set "L_TITLE=%~1"
set "L_DIR=%~2"
set "L_CMD=%~3"
set "L_COLOR=%~4"
if defined HAS_WT (
  wt -w %WT_WIN% new-tab --title "%L_TITLE%" --suppressApplicationTitle --tabColor "%L_COLOR%" -d "%L_DIR%" cmd /k "%L_CMD%"
  if not errorlevel 1 exit /b 0
  rem  wt.exe did not accept the command: drop every following tab back to a
  rem  normal console window so the services still start.
  set "HAS_WT="
)
start "%L_TITLE%" /D "%L_DIR%" cmd /k "%L_CMD%"
exit /b 0

:wait_port
set "WAIT_PORT=%~1"
set "WAIT_NAME=%~2"
set "WAIT_OK="
echo   Waiting for %WAIT_NAME% on port %WAIT_PORT% (up to 120 seconds)...
for /f "usebackq delims=" %%r in (`powershell -NoProfile -Command "$p=%WAIT_PORT%; $d=(Get-Date).AddSeconds(120); while((Get-Date) -lt $d){ try { $c=[Net.Sockets.TcpClient]::new('127.0.0.1',$p); $c.Close(); Write-Output 'OK'; break } catch { Start-Sleep -Milliseconds 500 } }"`) do set "WAIT_OK=%%r"
if defined WAIT_OK (
  echo   %WAIT_NAME% is ready.
) else (
  echo   [WARNING] %WAIT_NAME% is not listening on port %WAIT_PORT% after 120s.
  echo             Check its service window for the startup error.
)
exit /b 0

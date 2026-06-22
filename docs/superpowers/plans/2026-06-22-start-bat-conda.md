# start.bat Conda Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update `star.bat` so the backend window activates the `label_v2` Conda environment before running `python server.py`.

**Architecture:** Keep the existing dual-window launcher and frontend port auto-detection. Replace the backend branch's dependency-install fallback with Conda activation logic that first locates `conda.bat`, then activates `label_v2`, verifies `python` is available, and starts the backend inside that environment.

**Tech Stack:** Windows batch, Conda, PowerShell

---

### Task 1: Update Backend Launcher To Use Conda

**Files:**
- Modify: `star.bat`

- [ ] **Step 1: Replace backend dependency auto-install with Conda activation**

```bat
set "CONDA_BAT="
if defined CONDA_EXE if exist "%CONDA_EXE%" (
    for %%I in ("%CONDA_EXE%") do set "CONDA_BAT=%%~dpIconda.bat"
)
if not defined CONDA_BAT if exist "%USERPROFILE%\anaconda3\condabin\conda.bat" set "CONDA_BAT=%USERPROFILE%\anaconda3\condabin\conda.bat"
if not defined CONDA_BAT if exist "%USERPROFILE%\miniconda3\condabin\conda.bat" set "CONDA_BAT=%USERPROFILE%\miniconda3\condabin\conda.bat"

if not defined CONDA_BAT (
    echo [ERROR] 未找到 conda.bat，无法激活 label_v2 环境
    pause
    exit /b 1
)

call "%CONDA_BAT%" activate label_v2
if errorlevel 1 (
    echo [ERROR] 激活 conda 环境 label_v2 失败
    pause
    exit /b 1
)

python -c "import sys; print(sys.executable)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] label_v2 环境中的 Python 不可用
    pause
    exit /b 1
)
```

- [ ] **Step 2: Verify the backend dry-run branch still exits cleanly**

Run:

```bash
cd h:\Git\Label-fast-main
$env:STAR_DRY_RUN='1'; Start-Process -FilePath '.\star.bat' -ArgumentList 'backend' -RedirectStandardOutput '.\backend_dry_run.out' -RedirectStandardError '.\backend_dry_run.err' -Wait -PassThru -WindowStyle Hidden
```

Expected:

```text
exit=0
[DRY-RUN] backend ready: python server.py
```

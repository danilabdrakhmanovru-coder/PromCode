@echo off
chcp 65001 > nul
title ПромКод - Project Start

cd /d "%~dp0"

echo ============================================================
echo   ПромКод - project start
echo ============================================================
echo.

set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set http_proxy=
set https_proxy=
set all_proxy=

set "PYTHON_CMD="
where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=py -3"
    )
)

if "%PYTHON_CMD%"=="" (
    echo [ERROR] Python was not found.
    echo Install Python 3.11/3.12 and enable Add Python to PATH.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Creating virtual environment...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv
        pause
        exit /b 1
    )
) else (
    echo [1/5] Virtual environment already exists.
)

echo [2/5] Activating virtual environment...
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

echo [3/5] Installing dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [4/5] Creating .env file...
    if exist ".env.example" (
        copy ".env.example" ".env" > nul
    ) else (
        (
            echo DGIS_API_KEY=
            echo YANDEX_MAPS_API_KEY=
            echo LLM_API_KEY=
            echo LLM_USE_MOCK=true
            echo RENDER_MODE=procedural
        ) > ".env"
    )
) else (
    echo [4/5] .env already exists.
)

echo [5/5] Starting server...
echo.
echo Site: http://127.0.0.1:8000
echo To stop the server press Ctrl+C.
echo.

start "" "http://127.0.0.1:8000"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

pause

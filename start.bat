@echo off
setlocal enabledelayedexpansion

set OPENROUTER_KEY=
set OPENROUTER_MODEL_ARG=

:: Parse arguments
:parse_args
if "%~1"=="" goto done_args
if "%~1"=="--openrouter-key" (
    set OPENROUTER_KEY=%~2
    shift
    shift
    goto parse_args
)
if "%~1"=="--openrouter-model" (
    set OPENROUTER_MODEL_ARG=%~2
    shift
    shift
    goto parse_args
)
shift
goto parse_args
:done_args

echo ============================================
echo   LLM-LogicUpgrade - Starting...
echo ============================================
echo.

:: Copy .env if not exists
if not exist .env (
    copy .env.example .env
    echo [INFO] Created .env from .env.example
    echo.
)

:: Branch based on mode
if not "%OPENROUTER_KEY%"=="" goto mode_openrouter
goto mode_local

:: ============================================
:: OpenRouter mode
:: ============================================
:mode_openrouter
echo [MODE] OpenRouter - using cloud API

:: Write OpenRouter settings to .env
findstr /v "OPENROUTER_API_KEY OPENROUTER_MODEL" .env > .env.tmp
echo OPENROUTER_API_KEY=%OPENROUTER_KEY%>> .env.tmp
if not "%OPENROUTER_MODEL_ARG%"=="" echo OPENROUTER_MODEL=%OPENROUTER_MODEL_ARG%>> .env.tmp
move /y .env.tmp .env >nul
echo.

echo [1/2] Starting Docker services (no Ollama)...
docker compose up -d --build redis dali2 orchestrator web-ui

echo.
echo [2/2] Waiting for orchestrator...
:wait_orch_or
timeout /t 2 /nobreak >nul
curl -s http://localhost:8000/api/health >nul 2>&1
if errorlevel 1 goto wait_orch_or

echo.
echo ============================================
echo   LLM-LogicUpgrade is ready! [OpenRouter]
echo.
echo   Web UI:       http://localhost:3000
echo   Orchestrator: http://localhost:8000/docs
echo   DALI2:        http://localhost:8080
echo   Backend:      OpenRouter
echo ============================================
goto done

:: ============================================
:: Local Ollama mode
:: ============================================
:mode_local
echo [MODE] Local Ollama

echo [1/3] Starting Docker services...
docker compose up -d --build

echo.
echo [2/3] Waiting for Ollama to be ready...
:wait_ollama
timeout /t 2 /nobreak >nul
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 goto wait_ollama

echo [3/3] Pulling LLM model (first time may take a while)...
for /f "tokens=*" %%i in ('findstr OLLAMA_MODEL .env') do set %%i
if "%OLLAMA_MODEL%"=="" set OLLAMA_MODEL=qwen3.5:9b
docker compose exec -T ollama ollama pull %OLLAMA_MODEL%

echo.
echo ============================================
echo   LLM-LogicUpgrade is ready! [Local]
echo.
echo   Web UI:       http://localhost:3000
echo   Orchestrator: http://localhost:8000/docs
echo   DALI2:        http://localhost:8080
echo   Ollama:       http://localhost:11434
echo ============================================

:done
echo.
echo Press any key to open the Web UI...
pause >nul
start http://localhost:3000

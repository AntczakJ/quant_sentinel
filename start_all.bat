@echo off
:: ============================================================
:: start_all.bat — Uruchamia cały system Quant Sentinel
::
:: Uruchamia równocześnie:
::   1. FastAPI backend (port 8000)
::   2. Telegram bot + skaner rynku (run.py)
::   3. Frontend (Vite dev server, port 5173)  [OPCJONALNIE]
::
:: Użycie:
::   start_all.bat          - uruchamia backend + bot
::   start_all.bat frontend - uruchamia backend + bot + frontend
:: ============================================================

SETLOCAL
SET "ROOT=%~dp0"
SET "PYTHON=python"

echo.
echo ============================================================
echo  QUANT SENTINEL AI — System Startup
echo ============================================================
echo.

:: --- 1. FastAPI Backend (API dla frontendu) ---
echo [1/3] Uruchamiam FastAPI backend (port 8000)...
start "QS-Backend" cmd /k "cd /d %ROOT% && %PYTHON% api/main.py"
timeout /t 3 /nobreak >nul

:: --- 2. Telegram Bot + Scanner ---
echo [2/3] Uruchamiam Telegram bot + skaner rynku...
start "QS-TelegramBot" cmd /k "cd /d %ROOT% && %PYTHON% run.py"
timeout /t 2 /nobreak >nul

:: --- 3. Frontend (opcjonalnie) ---
IF "%1"=="frontend" (
    echo [3/3] Uruchamiam frontend Vite (port 5173)...
    start "QS-Frontend" cmd /k "cd /d %ROOT%frontend && npm run dev"
) ELSE (
    echo [3/3] Frontend pominiety (uruchom: start_all.bat frontend)
)

echo.
echo ============================================================
echo  System uruchomiony!
echo  - Backend API:   http://localhost:8000
echo  - API Docs:      http://localhost:8000/docs
echo  - Frontend:      http://localhost:5173  (jesli uruchomiony)
echo  - Telegram bot:  aktywny (sprawdz Telegram)
echo ============================================================
echo.
echo Aby zatrzymac system: zamknij okna "QS-Backend", "QS-TelegramBot"
echo.

:: Auto-start przy logowaniu Windows (opcja — odblokuj ponizej):
:: UWAGA: wymaga uruchomienia tego skryptu jako Administrator
:: schtasks /create /tn "QuantSentinel" /tr "%ROOT%start_all.bat" /sc onlogon /ru %USERNAME% /f

pause


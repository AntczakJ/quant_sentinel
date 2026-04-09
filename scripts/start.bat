@echo off
REM QUANT SENTINEL - Quick Start Script for Windows

echo.
echo ========================================
echo 🚀 QUANT SENTINEL - Starting Application
echo ========================================
echo.

REM Change to project directory
cd /d "C:\Users\Jan\PycharmProjects\quant_sentinel"

REM Check if .venv exists
if not exist ".venv\" (
    echo ❌ Virtual environment not found!
    echo Run: python -m venv .venv
    pause
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

echo.
echo 📡 Starting Backend API on port 8000...
echo.
start "Backend API" cmd /k python api/main.py
timeout /t 3 /nobreak

echo.
echo 🎨 Starting Frontend on port 5173...
echo.
cd "frontend"
start "Frontend" cmd /k npm run dev
timeout /t 2 /nobreak

cd ..

echo.
echo 🔍 Scanner - Start scanner in separate terminal?
echo.
choice /C YN /M "Start scanner [Y/N]? "
if errorlevel 2 goto :skip_scanner
if errorlevel 1 goto :start_scanner

:start_scanner
echo.
echo Starting Scanner...
echo.
start "Scanner" cmd /k python run.py
goto :done

:skip_scanner
echo Skipped scanner. You can start it later with: python run.py

:done
echo.
echo ========================================
echo ✅ QUANT SENTINEL - Started!
echo ========================================
echo.
echo Frontend: http://localhost:5173
echo Backend:  http://localhost:8000
echo API Docs: http://localhost:8000/docs
echo.
echo Close these windows to stop the application.
echo.
pause


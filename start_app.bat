@echo off
setlocal

cd /d "%~dp0"

set "PYTHON=python"
where python >nul 2>&1
if errorlevel 1 set "PYTHON=C:\Users\EGY-CRETE\AppData\Local\Programs\Python\Python314\python.exe"

if not exist "%PYTHON%" (
    echo Python was not found.
    echo Install Python or update the PYTHON path in this file.
    pause
    exit /b 1
)

echo Starting EGY-CRETE Market Opportunity App...
echo Keep this window open while using the app.
echo.

"%PYTHON%" -m streamlit run Market_Opportunity_app.py

if errorlevel 1 (
    echo.
    echo The app stopped because an error occurred.
    pause
)

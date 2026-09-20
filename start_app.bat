@echo off
cd /d "%~dp0"
streamlit run "Recrutment app.py" --server.headless true --server.port 8502
pause

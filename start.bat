@echo off

cd /d C:\Users\zahi\.venvs\GPT-SoVITS-v2pro-20250604
start "" ".\runtime\python.exe" api_v2.py -a 127.0.0.1 -p 9880

cd /d C:\Users\zahi\Desktop\dzxt\services\clone
start "" ".venv\Scripts\python.exe" main.py

cd /d C:\Users\zahi\Desktop\dzxt
start "" ".venv\Scripts\python.exe" -m server.main

cd web
npm run dev

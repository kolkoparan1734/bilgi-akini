@echo off
REM Bilgi Akini'yi tek komutla baslatir: backend + frontend ayri pencerelerde
REM acilir, birkac saniye sonra tarayici otomatik acilir.
cd /d "%~dp0"

start "Bilgi Akini - Backend" cmd /k "cd /d backend && venv\Scripts\python.exe app.py"
start "Bilgi Akini - Frontend" cmd /k "cd /d frontend && C:\Users\Thin\AppData\Local\Programs\Python\Python311\python.exe -m http.server 5500"

timeout /t 3 /nobreak >nul
start http://localhost:5500

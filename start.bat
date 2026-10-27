@echo off
REM ============================================================
REM  BILGI AKINI - tek tikla baslatici
REM  1) Python'u bulur (sabit yol yok), gerekirse kurulumu yapar
REM  2) Oyun sunucusunu ayri pencerede acar (oyun + API tek port)
REM  3) Sunucu gercekten hazir olana kadar bekler
REM  4) Bilgisayar ve telefon adreslerini yazar, tarayiciyi acar
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
title Bilgi Akini - Baslatici
set "PORT=5000"
set "VENV_PY=%~dp0backend\venv\Scripts\python.exe"
set "HEALTH=http://127.0.0.1:%PORT%/api/health"

echo.
echo  ==========================================
echo    BILGI AKINI baslatiliyor...
echo  ==========================================
echo.

REM --- Sunucu zaten acik mi? (start.bat iki kez calistirildiysa) ---
call :probe
if not errorlevel 1 (
  echo  Sunucu zaten calisiyor.
  goto ready
)

REM --- Port baska bir program tarafindan kullaniliyor mu? ---
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo  [HATA] %PORT% portu baska bir program tarafindan kullaniliyor.
  echo         Acik kalan eski bir sunucu penceresini kapatip tekrar dene.
  goto fail
)

REM --- Python ortami hazir mi? ---
if exist "%VENV_PY%" (
  "%VENV_PY%" -c "import flask, flask_socketio, flask_sqlalchemy, flask_cors" >nul 2>&1
  if not errorlevel 1 goto start_server
)

echo  Ilk kurulum yapiliyor (bir kez, internet gerekir)...
call :find_python
if not defined SYSPY (
  echo  [HATA] Python bulunamadi. https://www.python.org adresinden
  echo         Python 3.11 kurup "Add python.exe to PATH" kutusunu isaretle.
  goto fail
)
echo  Kullanilan Python: %SYSPY%
%SYSPY% -m venv "%~dp0backend\venv"
if errorlevel 1 (
  echo  [HATA] Sanal ortam olusturulamadi.
  goto fail
)
"%VENV_PY%" -m pip install --disable-pip-version-check -q -r "%~dp0backend\requirements.txt"
if errorlevel 1 (
  echo  [HATA] Paketler kurulamadi. Internet baglantisini kontrol et.
  goto fail
)

:start_server
echo  Oyun sunucusu aciliyor...
set "PYTHONIOENCODING=utf-8"
start "Bilgi Akini - Sunucu" /D "%~dp0backend" cmd /k ""%VENV_PY%" app.py"

REM --- Sunucu hazir olana kadar bekle (en fazla 30 sn) ---
set /a TRIES=0
:wait_loop
call :probe
if not errorlevel 1 goto ready
set /a TRIES+=1
if %TRIES% GEQ 30 goto timeout
timeout /t 1 /nobreak >nul
goto wait_loop

:timeout
echo.
echo  [HATA] Sunucu baslatilamadi.
echo         "Bilgi Akini - Sunucu" penceresindeki hata mesajina bak.
goto fail

:ready
echo.
echo  ==========================================
echo    OYUN HAZIR
echo  ==========================================
echo    Bilgisayar    : http://localhost:%PORT%
"%VENV_PY%" "%~dp0backend\netinfo.py" %PORT%
echo.
echo    Telefonda acilmiyorsa:
echo     - Telefon ve bilgisayar ayni Wi-Fi'da olmali
echo     - Windows Wi-Fi ag profili "Ozel" (Private) olmali
echo     - Guvenlik duvari sorarsa Python'a izin ver
echo  ==========================================
echo.
start "" "http://localhost:%PORT%"
echo  Bu pencereyi kapatabilirsin; sunucu diger pencerede calisiyor.
echo  Oyunu kapatmak icin "Bilgi Akini - Sunucu" penceresini kapat.
echo.
pause
exit /b 0

:fail
echo.
pause
exit /b 1

REM ---------- yardimci: sunucu cevap veriyor mu? (0 = evet) ----------
:probe
if not exist "%SystemRoot%\System32\curl.exe" goto probe_ps
"%SystemRoot%\System32\curl.exe" -s -f -o nul --max-time 2 "%HEALTH%" >nul 2>&1
exit /b %errorlevel%
:probe_ps
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%HEALTH%' | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
exit /b %errorlevel%

REM ---------- yardimci: sistemdeki Python'u bul ----------
:find_python
set "SYSPY="
for %%V in (3.11 3.12 3.13 3) do (
  if not defined SYSPY (
    py -%%V -c "import sys" >nul 2>&1 && set "SYSPY=py -%%V"
  )
)
if not defined SYSPY (
  python -c "import sys; assert sys.version_info >= (3, 9)" >nul 2>&1 && set "SYSPY=python"
)
exit /b 0

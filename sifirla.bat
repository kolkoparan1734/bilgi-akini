@echo off
REM ============================================================
REM  BILGI AKINI - sunum oncesi temizlik
REM  Test oyuncularini, altinlarini ve fetih ilerlemesini siler.
REM  Sorular, ulkeler, olaylar ve donemler KORUNUR.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
set "VENV_PY=%~dp0backend\venv\Scripts\python.exe"
set "DB=%~dp0backend\bilgi_akini.db"

if not exist "%DB%" (
  echo Veritabani bulunamadi; silinecek bir sey yok.
  pause
  exit /b 0
)

echo.
echo  Tum oyuncular, altinlar ve fetihler silinecek (Kumandanlar Siralamasi bosalir).
echo  Sorular ve haritadaki olaylar korunur.
echo.
choice /c EH /m " Devam edilsin mi? (E = evet, H = hayir)"
if errorlevel 2 (
  echo Iptal edildi.
  pause
  exit /b 0
)

"%VENV_PY%" -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); n=c.execute('select count(*) from players').fetchone()[0]; c.execute('delete from player_event_progress'); c.execute('delete from players'); c.commit(); print(f' {n} oyuncu silindi.')" "%DB%"
echo.
pause

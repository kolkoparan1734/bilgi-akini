@echo off
cd /d "%~dp0"
echo Frontend sunucusu baslatiliyor...
echo Tarayicida http://localhost:5500 adresini ac.
echo Bu pencereyi kapatma, oyunu kapatmak icin kapatabilirsin.
python -m http.server 5500
pause

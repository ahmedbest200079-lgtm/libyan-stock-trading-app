@echo off
chcp 65001 >nul
REM ── تثبيت متطلبات منظومة التغذية (مرة واحدة) ──
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || (
  echo [خطأ] بايثون غير مثبت. ثبّته من https://www.python.org/downloads/ مع اختيار "Add python.exe to PATH"
  pause & exit /b 1
)
%PY% -m pip install --upgrade pip
%PY% -m pip install -r "%~dp0tools\requirements.txt"
echo.
echo تم تثبيت المتطلبات بنجاح.
pause

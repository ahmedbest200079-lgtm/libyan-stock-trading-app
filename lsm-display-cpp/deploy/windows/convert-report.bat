@echo off
chcp 65001 >nul
REM ── تحويل تقرير واحد يدويًا: اسحب ملف التقرير (PDF أو Excel) وأفلته فوق هذا الملف ──
cd /d "%~dp0"
if "%~1"=="" ( echo اسحب ملف التقرير وأفلته فوق هذا الملف. & pause & exit /b 1 )
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% "%~dp0tools\lsm_feeder.py" "%~1" --out "%~dp0data\session.json" --companies "%~dp0data\companies.json"
pause

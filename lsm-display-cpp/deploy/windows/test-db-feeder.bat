@echo off
chcp 65001 >nul
REM ── اختبار الاتصال بقاعدة البيانات وعرض الأعمدة والنتيجة دون كتابة أي ملف ──
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% "%~dp0tools\lsm_db_feeder.py" --config "%~dp0tools\db_feeder.ini" --test
pause

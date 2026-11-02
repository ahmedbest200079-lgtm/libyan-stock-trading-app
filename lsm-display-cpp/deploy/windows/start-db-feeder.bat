@echo off
chcp 65001 >nul
REM ── التغذية المباشرة من قاعدة بيانات نظام التداول (دون تدخل بشري) ──
REM الإعداد في tools\db_feeder.ini — اختبره أولًا بـ test-db-feeder.bat
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
title LSM DB Feeder
:loop
%PY% "%~dp0tools\lsm_db_feeder.py" --config "%~dp0tools\db_feeder.ini"
echo توقفت التغذية — إعادة التشغيل خلال 15 ثانية...
timeout /t 15 >nul
goto loop

@echo off
chcp 65001 >nul
REM ── منظومة التغذية: تراقب مجلد التقارير وتحدّث الشاشة آليًا ──
REM عدّل المسار التالي إلى المجلد الذي تُحفظ فيه تقارير التداول اليومية
set REPORTS=C:\LSM\reports
cd /d "%~dp0"
if not exist "%REPORTS%" mkdir "%REPORTS%"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
title LSM Feeder - %REPORTS%
:loop
%PY% "%~dp0tools\lsm_feeder.py" --watch "%REPORTS%" --interval 15 --out "%~dp0data\session.json" --companies "%~dp0data\companies.json"
echo توقفت التغذية — إعادة التشغيل خلال 10 ثوانٍ...
timeout /t 10 >nul
goto loop

@echo off
chcp 65001 >nul
REM ── تسجيل التغذية كمهمة تبدأ مع إقلاع الجهاز (قبل تسجيل الدخول) — يُشغَّل كمسؤول ──
net session >nul 2>&1 || ( echo يجب تشغيل هذا الملف كمسؤول: زر أيمن ثم Run as administrator & pause & exit /b 1 )
schtasks /create /tn "LSM DB Feeder" /tr "\"%~dp0start-db-feeder.bat\"" /sc onstart /delay 0001:00 /ru SYSTEM /rl LIMITED /f
echo.
echo تم التسجيل. ملاحظة: كلمة مرور قاعدة البيانات يجب أن تكون متغير بيئة على مستوى النظام:
echo   setx LSM_DB_PASSWORD "..." /M
pause

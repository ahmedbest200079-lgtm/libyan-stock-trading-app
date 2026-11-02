@echo off
chcp 65001 >nul
REM ── شاشة العرض: ملء الشاشة، وإعادة التشغيل آليًا إن أُغلقت لأي سبب ──
REM عدّل SCALE حسب حجم الشاشة: 1 لشاشة 1080p، 1.5 أو 2 لشاشة 4K
set SCALE=1.25
cd /d "%~dp0"
:loop
"%~dp0lsm-market-display.exe" --fullscreen --scale %SCALE%
timeout /t 5 >nul
goto loop

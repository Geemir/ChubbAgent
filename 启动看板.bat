@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ChubbSafes 竞品监测看板

echo ============================================================
echo   ChubbSafes 竞品监测看板  正在启动...
echo   请保持本窗口开启；关闭本窗口即停止看板。
echo ============================================================
echo.

REM 4 秒后自动用默认浏览器打开看板页面（等服务启动完成）
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8010"

REM 启动看板（占用本窗口，日志在此显示）
py -m uv run chubb-ci dashboard --host 127.0.0.1 --port 8010

echo.
echo 看板已停止。按任意键关闭窗口。
pause >nul

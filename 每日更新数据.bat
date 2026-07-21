@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ChubbSafes 竞品监测 - 更新数据

echo ============================================================
echo   正在抓取竞品最新数据并生成日报...
echo   （也可在看板右上角点「运行抓取」完成同样操作）
echo ============================================================
echo.

py -m uv run chubb-ci crawl --kind daily --report

echo.
echo 完成。可打开看板查看最新结果。
pause

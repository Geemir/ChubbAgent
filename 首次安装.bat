@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ChubbSafes 竞品监测 - 首次安装

echo ============================================================
echo   ChubbSafes 竞品监测  首次安装
echo   仅需在新电脑上运行一次；之后每天用「启动看板.bat」即可。
echo ============================================================
echo.

echo [1/4] 检查 Python...
py --version
if errorlevel 1 (
  echo.
  echo × 未检测到 Python。请先安装 Python 3.13：https://www.python.org/downloads/
  echo   安装时请勾选 "Add Python to PATH"。装好后重新运行本文件。
  pause & exit /b 1
)

echo.
echo [2/4] 检查 uv 包管理器（缺失则自动安装）...
py -m uv --version 2>nul || py -m pip install uv

echo.
echo [3/4] 安装项目依赖（首次较慢，请耐心等待）...
py -m uv sync
if errorlevel 1 ( echo × 依赖安装失败，请检查网络后重试。 & pause & exit /b 1 )

echo.
echo [4/4] 安装浏览器内核（用于电商价格抓取）...
py -m uv run playwright install chromium chromium-headless-shell

echo.
echo ============================================================
echo   安装完成！
echo   - 确认根目录的 .env 文件已填好各项密钥（DeepSeek / 邮箱 / 搜索等）。
echo   - 之后双击「启动看板.bat」即可打开看板。
echo ============================================================
pause

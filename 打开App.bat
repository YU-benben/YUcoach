@echo off
chcp 65001 >nul
title YUcoach 分析服务
cd /d "%~dp0"

echo ====================================================================
echo   YUcoach 分析服务
echo ====================================================================
echo.
echo   这个窗口是手机 App 的"后台"——关闭它手机就连不上了。
echo   保持窗口开着，在手机上操作 App 即可。
echo.
echo   按 Ctrl+C 停止服务。
echo.
echo --------------------------------------------------------------------
echo.

rem --------------------------------------------------------------------
rem 解释器选择：优先项目内的 .venv（Python 3.13 + CUDA torch）。
rem 用显式路径而不是裸 python —— 裸 python 会跟着 PATH 走，
rem 换机器或删掉某个 Python 安装后会静默换成别的解释器（可能没有 CUDA）。
rem --------------------------------------------------------------------
set "YUCOACH_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%YUCOACH_PY%" (
    echo [WARN] 没找到项目内的 .venv，回退到 PATH 里的 python。
    echo         若姿态提取异常缓慢，多半是这个 python 没有 CUDA 版 torch。
    echo         重建方式见 README「开发 - 环境」。
    echo.
    set "YUCOACH_PY=python"
)

"%YUCOACH_PY%" -m backend.server.app --host 0.0.0.0 --port 8770

echo.
echo ====================================================================
echo   服务已停止
echo ====================================================================
echo.
echo   若上面出现 "python 不是内部或外部命令"，说明 Python 没装好，
echo   或没加进 PATH。
echo.
pause

@echo off
rem ====================================================================
rem  YUcoach analysis service launcher
rem
rem  IMPORTANT - why this file contains NO Chinese characters:
rem
rem    cmd.exe parses .bat files using the system ANSI code page
rem    (GBK on a Chinese Windows), NOT UTF-8. A UTF-8 file full of
rem    Chinese makes cmd mis-read the bytes, which shifts line breaks
rem    and produces errors like:
rem
rem        'backend.server.app' is not recognized as an internal command
rem
rem    i.e. even the command line itself gets shredded, and the service
rem    never starts. `chcp 65001` does NOT help: the line is already
rem    parsed by the time it executes.
rem
rem    So: keep this file pure ASCII. All Chinese messages are printed
rem    by the Python process below, which handles its own encoding.
rem ====================================================================

setlocal
chcp 65001 >nul
title YUcoach - Analysis Service
cd /d "%~dp0"

echo ====================================================================
echo   YUcoach - Short Sprint Form Analysis Service
echo ====================================================================
echo.
echo   This window is the backend of the phone App.
echo   Keep it open - the phone cannot connect once it is closed.
echo.
echo   Press Ctrl+C to stop.
echo.
echo --------------------------------------------------------------------
echo.

rem --------------------------------------------------------------------
rem  Interpreter selection: prefer the project-local .venv
rem  (Python 3.13; GPU optional for experimental inference).
rem
rem  Use an explicit path instead of a bare "python": a bare name follows
rem  PATH, so after uninstalling or replacing a Python installation it can
rem  silently resolve to a different interpreter with missing dependencies.
rem --------------------------------------------------------------------
set "YUCOACH_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%YUCOACH_PY%" goto :no_venv

"%YUCOACH_PY%" -m backend.server.app --host 0.0.0.0 --port 8770
set "RC=%ERRORLEVEL%"
goto :done

:no_venv
echo [ERROR] Project virtual environment not found:
echo         %YUCOACH_PY%
echo.
echo   This project runs from its own .venv, not from a system Python.
echo   Rebuild it with:
echo.
echo       py -3.13 -m venv --copies .venv
echo       .venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
echo   See README.md for setup and optional GPU dependencies.
echo   Manual contact timing does not run a pose model.
echo.
set "RC=1"

:done
echo.
echo ====================================================================
echo   Service stopped (exit code %RC%)
echo ====================================================================
echo.
echo   If the phone showed "Failed to connect" while the service WAS
echo   running, check these in order:
echo.
echo     1. Same network?      Phone and PC must be on one WiFi/hotspot.
echo     2. Right IP?          Use the "Phone access" address printed
echo                           ABOVE - it changes when the network does.
echo     3. Firewall allowed?  The service warns if the port is blocked.
echo     4. Phone hotspot?     Turn OFF "AP isolation" in the hotspot
echo                           settings, or the PC cannot reach the phone.
echo.
pause
endlocal

@echo off
setlocal
cd /d "%~dp0"
if defined VISION_RSI_PYTHON (
    if not exist "%VISION_RSI_PYTHON%" goto invalid_python
    set "AGENT_PYTHON=%VISION_RSI_PYTHON%"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "AGENT_PYTHON=%~dp0.venv\Scripts\python.exe"
) else (
    set "AGENT_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
)
if exist "%AGENT_PYTHON%" (
    "%AGENT_PYTHON%" -X utf8 launch_agent.py %*
) else (
    python -X utf8 launch_agent.py %*
)
exit /b %errorlevel%
:invalid_python
echo VISION_RSI_PYTHON must name an existing Python executable. 1>&2
exit /b 2

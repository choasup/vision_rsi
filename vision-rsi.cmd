@echo off
setlocal
set "AGENT_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%AGENT_PYTHON%" (
    "%AGENT_PYTHON%" -X utf8 "%~dp0launch_agent.py" --cli %*
) else (
    python -X utf8 "%~dp0launch_agent.py" --cli %*
)
exit /b %errorlevel%

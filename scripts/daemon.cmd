@echo off
rem Wrapper: activate .venv and run the idea-site daemon.
rem Required env (set these in Windows user vars or before calling this script):
rem   IDEA_SITE_REPO       = absolute path to the private idea-site clone
rem   IDEA_PIPELINE_REPO   = absolute path to youtube-subtitle-extractor
rem
rem Optional env:
rem   DAEMON_TICK_SECONDS            default 90
rem   DAEMON_STUCK_AGE_SECONDS       default 900
rem   DAEMON_MAX_ATTEMPTS            default 3
rem   DAEMON_RETRY_COOLDOWN_SECONDS  default 600
rem   DAEMON_CLAUDE_TIMEOUT_SECONDS  default 2700
rem   DAEMON_CLAUDE_MAX_BUDGET_USD   default 5

setlocal

set SCRIPT_DIR=%~dp0
set REPO_ROOT=%SCRIPT_DIR%..

if exist "%REPO_ROOT%\.venv\Scripts\activate.bat" (
  call "%REPO_ROOT%\.venv\Scripts\activate.bat"
) else (
  echo [daemon.cmd] no .venv found at %REPO_ROOT%\.venv — using system Python
)

python "%SCRIPT_DIR%daemon.py" %*
exit /b %ERRORLEVEL%

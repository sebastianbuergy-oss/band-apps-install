@echo off
REM Buergys Builds - Windows launcher.
setlocal
set "BB_ROOT=%~dp0.."
py -3 -c "import sys" >nul 2>&1 && (set "BB_PY=py -3") || (set "BB_PY=python")
pushd "%BB_ROOT%"
%BB_PY% -m bb.cli %*
set "BB_RC=%ERRORLEVEL%"
popd
exit /b %BB_RC%

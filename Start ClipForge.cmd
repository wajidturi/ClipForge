@echo off
rem Double-click to start ClipForge (API + workers) and open it in the browser.
rem Close this window (or press Ctrl+C) to stop the app.
title ClipForge
cd /d "%~dp0"
where uv >nul 2>nul || (echo uv was not found. Run scripts\setup.ps1 first. & pause & exit /b 1)
if not exist "frontend\dist\index.html" (
  echo Building the web app once...
  pushd frontend && call npm run build && popd
)
rem open the browser once the server had a few seconds to start
start "" /b cmd /c "timeout /t 8 /nobreak >nul & start "" http://localhost:8800"
uv run --project backend clipforge dev
echo.
echo ClipForge stopped.
pause

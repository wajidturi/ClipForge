# Start the backend (API + workers) in a new window and the Vite dev server here.
# Open http://localhost:5173 ; stop with Ctrl+C here and close the backend window.
$root = Split-Path -Parent $PSScriptRoot
Start-Process powershell -ArgumentList '-NoExit', '-Command', "Set-Location '$root\backend'; uv run clipforge dev"
Set-Location "$root\frontend"
npm run dev

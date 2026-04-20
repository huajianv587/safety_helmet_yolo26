@echo off
setlocal
cd /d "%~dp0"

if not exist "dist\index.html" (
  echo Static bundle not found. Run npm run build:static first.
  exit /b 1
)

echo Serving dist on http://127.0.0.1:9000 ...
cd /d "%CD%\dist"
python -m http.server 9000

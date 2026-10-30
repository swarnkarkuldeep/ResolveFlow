@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo [1/4] Checking Docker...
docker info >nul 2>&1
if not errorlevel 1 goto docker_ok

set "DD=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
if not exist "!DD!" (
  echo Docker Desktop is not installed or not found. Install it from https://www.docker.com/products/docker-desktop
  exit /b 1
)
echo Docker is not running. Starting Docker Desktop...
start "" "!DD!"
set /a tries=0
:wait_docker
docker info >nul 2>&1
if not errorlevel 1 goto docker_ok
set /a tries+=1
if !tries! GEQ 60 (
  echo Docker Desktop failed to start within 2 minutes.
  exit /b 1
)
timeout /t 2 /nobreak >nul
goto wait_docker

:docker_ok
if not exist .env copy .env.example .env >nul

set WEB_PORT=3000
set API_PORT=8000
for /f "tokens=2 delims==" %%a in ('findstr /b "WEB_PORT=" .env') do set WEB_PORT=%%a
for /f "tokens=2 delims==" %%a in ('findstr /b "API_PORT=" .env') do set API_PORT=%%a

echo [2/4] Building and starting containers (first run takes a few minutes)...
docker compose up -d --build
if errorlevel 1 (
  echo.
  echo Startup failed. If a port is already in use, change WEB_PORT / API_PORT / DB_PORT / REDIS_PORT / MAILPIT_UI_PORT in .env and run again.
  exit /b 1
)

echo [3/4] Waiting for the API to become ready...
set /a tries=0
:wait_api
curl -sf "http://localhost:%API_PORT%/api/health/ready" >nul 2>&1
if not errorlevel 1 goto api_ok
set /a tries+=1
if !tries! GEQ 90 (
  echo API did not become ready. Run "docker compose logs api" to see why.
  exit /b 1
)
timeout /t 2 /nobreak >nul
goto wait_api

:api_ok
echo [4/4] Ready.
echo   App:     http://localhost:%WEB_PORT%
echo   Mailpit: http://localhost:8025
start "" "http://localhost:%WEB_PORT%"
exit /b 0

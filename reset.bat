@echo off
cd /d "%~dp0"
echo This deletes ALL ResolveFlow data (database volumes).
set /p confirm=Type y to continue: 
if /i not "%confirm%"=="y" (
  echo Cancelled.
  exit /b 1
)
docker compose down -v

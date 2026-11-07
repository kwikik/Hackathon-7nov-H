@echo off
rem Ferme l'interface de demo Cerfa : le serveur, l'agent en cours et la fenetre Chromium de l'agent.
rem Arrete TOUS les serveurs qui ecoutent sur le port (y compris un vieux serveur oublie).
cd /d "%~dp0"

set DEMO_PORT=8765
for /f "tokens=2 delims==" %%a in ('findstr /b "DEMO_PORT=" .env 2^>nul') do set DEMO_PORT=%%a

set FOUND=
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:%DEMO_PORT% .*LISTENING"') do (
  set FOUND=1
  rem /T : tue aussi les enfants (agent.py, Playwright, Chromium)
  taskkill /PID %%p /T /F >nul 2>&1
  echo Serveur arrete (PID %%p^).
)
if not defined FOUND echo Aucun serveur de demo sur le port %DEMO_PORT%.

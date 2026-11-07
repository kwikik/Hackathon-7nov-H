@echo off
rem Lance l'interface de demo Cerfa et ouvre le navigateur.
rem Le serveur tourne dans une fenetre reduite "Cerfa demo". Pour tout fermer : stop_demo.bat
cd /d "%~dp0"

set DEMO_PORT=8765
for /f "tokens=2 delims==" %%a in ('findstr /b "DEMO_PORT=" .env 2^>nul') do set DEMO_PORT=%%a
rem curl.exe (inclus dans Windows) plutot qu'Invoke-WebRequest : ce dernier cherche
rem un proxy reseau et peut bloquer de longues secondes.
set PING=curl.exe -s -o nul -m 1 http://127.0.0.1:%DEMO_PORT%/state

rem Deja lance ? On ouvre juste la page.
%PING% && (
  echo Serveur deja lance sur le port %DEMO_PORT%.
  goto open
)

start "Cerfa demo" /min py -3.13 demo_server.py

rem Attend que le serveur reponde (20 s max) avant d'ouvrir le navigateur.
for /l %%i in (1,1,20) do (
  %PING% && goto open
  rem pause ~1 s (timeout echoue si l entree est redirigee)
  ping -n 2 127.0.0.1 >nul
)
echo Le serveur ne repond pas. Regarde la fenetre "Cerfa demo".
pause
exit /b 1

:open
echo Cerfa demo -^> http://localhost:%DEMO_PORT%
start "" http://localhost:%DEMO_PORT%

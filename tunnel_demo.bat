@echo off
rem Publie la demo sur Internet via un tunnel Cloudflare : https://xxx.trycloudflare.com
rem Le jury ouvre le lien, saisit le mot de passe (DEMO_PASSWORD du .env), et pilote la vraie demo.
rem Ctrl+C coupe le tunnel ; la demo locale continue. Pour tout fermer : stop_demo.bat
cd /d "%~dp0"

rem Juste apres l'installation, le PATH du terminal n'est pas encore a jour :
rem on cherche aussi a l'emplacement par defaut de l'installeur.
set "CF="
where cloudflared >nul 2>&1 && set "CF=cloudflared"
if not defined CF if exist "%ProgramFiles(x86)%\cloudflared\cloudflared.exe" set "CF=%ProgramFiles(x86)%\cloudflared\cloudflared.exe"
if not defined CF (
  echo cloudflared n'est pas installe. Lance : winget install --id Cloudflare.cloudflared
  pause
  exit /b 1
)
findstr /b /r /c:"DEMO_PASSWORD=." .env >nul 2>&1
if errorlevel 1 (
  echo DEMO_PASSWORD est vide dans .env : l'acces par le tunnel serait refuse.
  pause
  exit /b 1
)

call "%~dp0start_demo.bat"
if errorlevel 1 exit /b 1

echo.
echo ================================================================
echo  Lien public : l'adresse https://....trycloudflare.com ci-dessous
echo  Identifiant : libre (ex. jury)   Mot de passe : DEMO_PASSWORD du .env
echo  Le lien change a chaque lancement. Ctrl+C pour couper le tunnel.
echo ================================================================
echo.
"%CF%" tunnel --no-autoupdate --url http://127.0.0.1:%DEMO_PORT%

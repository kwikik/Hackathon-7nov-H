@echo off
rem Lance l'interface de demo Cerfa et ouvre le navigateur.
cd /d "%~dp0"
py -3.13 demo_server.py
pause

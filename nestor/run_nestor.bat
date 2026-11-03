@echo off
chcp 65001 >nul
rem NeSToR — локальный запуск на Windows. Нужен Python 3.10+ (python.org), сторонние пакеты не нужны.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 run_nestor.py %*) || (python run_nestor.py %*)
pause

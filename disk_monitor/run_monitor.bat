@echo off
rem ============================================================
rem  disk_monitor 実行用バッチ
rem  タスクスケジューラから30分おきなどに実行する。
rem  実行状況(エラー含む)を log\log_YYYYMMDDHHMMSS.log に保存する。
rem ============================================================
setlocal

rem python.exe が PATH に無い場合はフルパスに書き換える
rem 例: set PYTHON=C:\Python37\python.exe
set PYTHON=python

cd /d "%~dp0"

if not exist "%~dp0log" mkdir "%~dp0log"

rem %date%/%time% はロケール依存なので PowerShell でタイムスタンプ生成
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMddHHmmss"') do set LOGSTAMP=%%i
set LOGFILE=%~dp0log\log_%LOGSTAMP%.log

echo ===== disk_monitor start %DATE% %TIME% ===== >> "%LOGFILE%" 2>&1
"%PYTHON%" "%~dp0disk_monitor.py" >> "%LOGFILE%" 2>&1
set RC=%ERRORLEVEL%
echo ===== disk_monitor end %DATE% %TIME% exitcode=%RC% ===== >> "%LOGFILE%"

rem 30日より古いログを削除
forfiles /p "%~dp0log" /m log_*.log /d -30 /c "cmd /c del @path" >nul 2>&1

endlocal & exit /b %RC%

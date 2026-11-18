@echo off
rem ============================================================
rem  wip_stat.YYYYMMDD を期間指定で集めてZIP化する
rem
rem  使い方: wip_zip.bat [開始日YYYYMMDD] [終了日YYYYMMDD]
rem    引数省略時は setting.json の start_date / end_date
rem    (既定: 20240101 ～ 昨日)
rem
rem  設定は同じフォルダの setting.json
rem  7-Zip (7z.exe) が必要。PATH に無い場合は setting.json の
rem  seven_zip にフルパスを書く
rem ============================================================
setlocal

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0collect_wip_zip.ps1" %1 %2
set RC=%ERRORLEVEL%

endlocal & exit /b %RC%

@echo off
rem ============================================================
rem  wip_stat.YYYYMMDD を期間指定で集めてZIP化する
rem
rem  使い方: wip_zip.bat [開始日YYYYMMDD] [終了日YYYYMMDD]
rem    引数省略時は下記 CFG_START / CFG_END (既定: 20240101 ～ 昨日)
rem
rem  7-Zip (7z.exe) が必要。PATH or Program Files から自動検出。
rem  見つからない・別パスに入れてる場合は CFG_7Z にフルパスを書く
rem ============================================================
setlocal

rem ==================== 設定 (ここを編集) ====================
rem 保存ルート
set "CFG_ROOT=\\10.20.24.88\load4"
rem 対象ファイル名のプレフィックス
set "CFG_PREFIX=wip_stat"
rem 期間の既定 (YYYYMMDD または yesterday/today)
set "CFG_START=20240101"
set "CFG_END=yesterday"
rem ZIP出力先 (相対ならこのbatのフォルダ基準)
set "CFG_OUTDIR=output"
rem ZIP名 ({start}/{end} が期間に置き換わる)
set "CFG_ZIPNAME=wip_stat_{start}_{end}.zip"
rem 7z.exe のパス (空なら PATH/Program Files から自動検出)
set "CFG_7Z="
rem 検索対象: 「相対パス:recursive(true/false)」を ; 区切りで列挙
rem   相対パスが空 = ルート直下のみ。stock_data は年月階層ごと再帰。
rem   2025年分が将来 stock_data に移動しても変更不要 (再帰で拾える)
set "CFG_DIRS=stock_data:true;:false"
rem ==========================================================

cd /d "%~dp0"

rem このファイル末尾のPowerShellを取り出して実行する
rem (パス・引数は環境変数経由で渡す。コマンド列への埋め込みだと
rem  ' や & を含むパスで壊れるため)
set "SRCBAT=%~f0"
set "SDIR=%~dp0."
set "WZIP_START=%~1"
set "WZIP_END=%~2"
for /f "delims=: tokens=1" %%i in ('findstr /n "^### POWERSHELL ###" "%~f0"') do set "SKIP=%%i"
if not defined SKIP (echo marker not found 1>&2 & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$l=[IO.File]::ReadAllLines($env:SRCBAT,[Text.Encoding]::GetEncoding(932)); $sb=[ScriptBlock]::Create((($l|Select-Object -Skip $env:SKIP) -join [Environment]::NewLine)); & $sb $env:SDIR $env:WZIP_START $env:WZIP_END"
set RC=%ERRORLEVEL%

endlocal & exit /b %RC%

### POWERSHELL ###
param(
  [string]$ScriptDir,
  [string]$StartDate,
  [string]$EndDate
)

$ErrorActionPreference = 'Stop'
$scriptDir = $ScriptDir.TrimEnd('\')

# 設定はbat先頭の set "CFG_*" 変数から環境変数経由で来る
$config = [pscustomobject]@{
  root_folder = $env:CFG_ROOT
  file_prefix = if ($env:CFG_PREFIX)  { $env:CFG_PREFIX }  else { 'wip_stat' }
  start_date  = if ($env:CFG_START)   { $env:CFG_START }   else { '20240101' }
  end_date    = if ($env:CFG_END)     { $env:CFG_END }     else { 'yesterday' }
  output_dir  = $env:CFG_OUTDIR
  zip_name    = if ($env:CFG_ZIPNAME) { $env:CFG_ZIPNAME } else { 'wip_stat_{start}_{end}.zip' }
  seven_zip   = $env:CFG_7Z
  scan_dirs   = @()
}
foreach ($e in ($env:CFG_DIRS -split ';')) {
  $p = $e -split ':', 2
  if ($p.Count -eq 2) {
    $config.scan_dirs += [pscustomobject]@{ path = $p[0].Trim(); recursive = ($p[1].Trim() -eq 'true') }
  }
}

function Resolve-Date([string]$v) {
  $v = "$v".Trim('"')
  if ($v -eq '') { throw '日付が未指定です' }
  if ($v -eq 'yesterday') { return (Get-Date).AddDays(-1).ToString('yyyyMMdd') }
  if ($v -eq 'today')     { return (Get-Date).ToString('yyyyMMdd') }
  if ($v -notmatch '^\d{8}$') { throw "日付の形式が不正です: $v (YYYYMMDD または yesterday/today)" }
  try {
    [void][datetime]::ParseExact($v, 'yyyyMMdd', [Globalization.CultureInfo]::InvariantCulture)
  } catch {
    throw "存在しない日付です: $v"
  }
  return $v
}

$start = Resolve-Date $(if ($StartDate) { $StartDate } else { $config.start_date })
$end   = Resolve-Date $(if ($EndDate)   { $EndDate }   else { $config.end_date })
if ($start -gt $end) { throw "開始日が終了日より後です: $start > $end" }

$root = $config.root_folder
if (-not (Test-Path -LiteralPath $root)) { throw "ルートフォルダにアクセスできません: $root" }

# 対象ファイルを収集 (拡張子=日付なので文字列比較で期間判定できる)
$files = @{}
foreach ($d in $config.scan_dirs) {
  $dir = if ([string]::IsNullOrEmpty($d.path)) { $root } else { Join-Path $root $d.path }
  if (-not (Test-Path -LiteralPath $dir)) { Write-Host "スキップ(フォルダなし): $dir"; continue }
  $opt = @{ LiteralPath = $dir; File = $true; Filter = "$($config.file_prefix).*" }
  if ($d.recursive) { $opt.Recurse = $true }
  Get-ChildItem @opt | ForEach-Object {
    $ext = $_.Extension -replace '^\.', ''
    if ($ext -match '^\d{8}$' -and $ext -ge $start -and $ext -le $end) {
      if (-not $files.ContainsKey($_.Name)) { $files[$_.Name] = $_.FullName }
    }
  }
}

if ($files.Count -eq 0) {
  Write-Host "対象ファイルがありません ($start - $end)"
  exit 1
}
Write-Host "対象: $($files.Count) 件 ($start - $end)"

# 7z 用リストファイル (UTF-8 BOMなし。BOMが先頭パスに混入するのを防ぐ)
$listFile = Join-Path $env:TEMP "wip_zip_list_$([guid]::NewGuid().ToString('N')).txt"
try {
  $sorted = $files.Values | Sort-Object
  [System.IO.File]::WriteAllLines($listFile, [string[]]$sorted, (New-Object System.Text.UTF8Encoding $false))

  # 出力先
  $outDir = $config.output_dir
  if ([string]::IsNullOrEmpty($outDir)) { $outDir = '.' }
  if (-not [System.IO.Path]::IsPathRooted($outDir)) { $outDir = Join-Path $scriptDir $outDir }
  New-Item -ItemType Directory -Force -Path $outDir | Out-Null
  $zipName = ($config.zip_name -replace '\{start\}', $start) -replace '\{end\}', $end
  $zipPath = Join-Path $outDir $zipName
  # 失敗時に既存ZIPを消さないよう、別名で作成してから置き換える
  $tmpZip = "$zipPath.tmp"
  if (Test-Path -LiteralPath $tmpZip) { Remove-Item -LiteralPath $tmpZip -Force }

  # 7z.exe: CFG_7Z 指定があればそれ、なければ PATH → Program Files を探す
  $sevenZip = $config.seven_zip
  if ([string]::IsNullOrEmpty($sevenZip)) {
    $sevenZip = (Get-Command 7z.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
    if (-not $sevenZip) {
      $candidates = @((Join-Path $env:ProgramFiles '7-Zip\7z.exe'))
      if (${env:ProgramFiles(x86)}) { $candidates += Join-Path ${env:ProgramFiles(x86)} '7-Zip\7z.exe' }
      $sevenZip = ($candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1)
    }
    if (-not $sevenZip) { throw '7z.exe が見つかりません。7-Zipをインストールするか CFG_7Z にフルパスを書いてください' }
  }

  & $sevenZip a $tmpZip -tzip -scsUTF-8 "-i@$listFile"
  if ($LASTEXITCODE -ne 0) { throw "7z が失敗しました (exit=$LASTEXITCODE)" }
  if (-not (Test-Path -LiteralPath $tmpZip)) { throw "ZIPが作成されませんでした: $tmpZip" }
  Move-Item -LiteralPath $tmpZip -Destination $zipPath -Force

  $size = (Get-Item -LiteralPath $zipPath).Length
  Write-Host "作成完了: $zipPath ($('{0:N0}' -f $size) bytes)"
  exit 0
}
finally {
  Remove-Item -LiteralPath $listFile -Force -ErrorAction SilentlyContinue
}

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

rem このファイル末尾のPowerShellを取り出して実行する
rem (パスは環境変数経由で渡す。コマンド列への埋め込みだと
rem  ' を含むパスで壊れるため)
set SRCBAT=%~f0
set SDIR=%~dp0.
set WZIP_START=%1
set WZIP_END=%2
for /f "delims=: tokens=1" %%i in ('findstr /n "^### POWERSHELL ###" "%~f0"') do set SKIP=%%i
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
$config = Get-Content -LiteralPath (Join-Path $scriptDir 'setting.json') -Raw -Encoding UTF8 | ConvertFrom-Json

function Resolve-Date([string]$v) {
  if ($v -eq '' -or $null -eq $v) { throw '日付が未指定です' }
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

  & $config.seven_zip a $tmpZip -tzip -scsUTF-8 "-i@$listFile"
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

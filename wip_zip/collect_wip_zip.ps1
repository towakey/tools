# wip_stat.YYYYMMDD を期間指定で集めてZIP化する
# 引数: collect_wip_zip.ps1 [開始日YYYYMMDD] [終了日YYYYMMDD]
#   省略時は setting.json の start_date / end_date
param(
  [string]$StartDate,
  [string]$EndDate
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$config = Get-Content -LiteralPath (Join-Path $scriptDir 'setting.json') -Raw -Encoding UTF8 | ConvertFrom-Json

function Resolve-Date([string]$v) {
  if ($v -eq '' -or $null -eq $v) { throw '日付が未指定です' }
  if ($v -eq 'yesterday') { return (Get-Date).AddDays(-1).ToString('yyyyMMdd') }
  if ($v -eq 'today')     { return (Get-Date).ToString('yyyyMMdd') }
  if ($v -notmatch '^\d{8}$') { throw "日付の形式が不正です: $v (YYYYMMDD または yesterday/today)" }
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
  if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }

  & $config.seven_zip a $zipPath -tzip -scsUTF-8 "-i@$listFile"
  if ($LASTEXITCODE -ne 0) { throw "7z が失敗しました (exit=$LASTEXITCODE)" }
  if (-not (Test-Path -LiteralPath $zipPath)) { throw "ZIPが作成されませんでした: $zipPath" }

  $size = (Get-Item -LiteralPath $zipPath).Length
  Write-Host "作成完了: $zipPath ($('{0:N0}' -f $size) bytes)"
  exit 0
}
finally {
  Remove-Item -LiteralPath $listFile -Force -ErrorAction SilentlyContinue
}

@echo off
setlocal
set "BAT_FILE=%~f0"

REM ===== 設定項目（TUIの初期値）=====
REM 対象ディレクトリ（%CD% で実行時のカレントディレクトリ、%~dp0 でこのBATと同じ階層）
set "TARGET_DIR=%CD%"
REM 圧縮対象の拡張子をスペース区切りで指定（空欄＝全ての拡張子）
set "INCLUDE_EXTS="
REM 圧縮しない拡張子をスペース区切りで指定
set "EXCLUDE_EXTS=zip bat"
REM 検索文字列（引数があれば初期値として使用）
set "TARGET_PATTERN=%~1"

REM 画面(TUI_START行以降)と処理本体(PS_START行以降)はこのファイル末尾にPowerShellで記述
REM （1行が長いとCMDのgotoが固まるため、処理本体は複数行で記述）
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:BAT_FILE,[Text.Encoding]::Default); $i=$s.IndexOf('#'+'TUI_START'); iex $s.Substring($i,$s.IndexOf('#'+'PS_START')-$i)"
exit /b 0

#TUI_START
$names='TARGET_PATTERN','TARGET_DIR','INCLUDE_EXTS','EXCLUDE_EXTS'
$labels='検索文字列　　　','対象ディレクトリ','対象拡張子　　　','除外拡張子　　　','[ 実行 ]','[ 終了 ]'
$v=@{}
foreach($n in $names){ $v[$n]=[string][Environment]::GetEnvironmentVariable($n) }
$body='Set-Location -LiteralPath $env:TARGET_DIR'+"`n"+$s.Substring($s.IndexOf('#'+'PS_START'))
$enc=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($body))
$psExe=(Get-Process -Id $PID).Path
$sel=0

# 全角は2桁として行末まで空白で埋める（再描画時の残りカスを消す）
# shortcut: 画面幅を超える値は折り返して表示が崩れる、問題になったら表示を切り詰める
function Line($t,$hi){
  $len=0
  foreach($c in $t.ToCharArray()){ $len+=$(if([int]$c -gt 0xFF){2}else{1}) }
  $w=[Console]::WindowWidth-1
  if($len -lt $w){ $t+=' '*($w-$len) }
  if($hi){ Write-Host $t -ForegroundColor Black -BackgroundColor Gray } else { Write-Host $t }
}

function Draw {
  [Console]::SetCursorPosition(0,0)
  Line '=================================================='
  Line '  ログ圧縮ツール'
  Line '=================================================='
  Line ''
  for($i=0; $i -lt 6; $i++){
    if($i -lt 4){ $t='  '+$labels[$i]+': '+$v[$names[$i]]; if($i -eq $sel){ $t+='_' } }
    else { if($i -eq 4){ Line '' }; $t='  '+$labels[$i] }
    Line $t ($i -eq $sel)
  }
  Line ''
  Line '  ↑↓:移動  文字入力:編集  BackSpace:1文字削除  Delete:全消去'
  Line '  Enter:次の項目／実行（対象ディレクトリは選択モード）  Esc:終了'
  Line '  ※対象拡張子が空欄の場合は全ての拡張子が対象'
  Line '=================================================='
}

# 対象ディレクトリ選択モード。→:中へ ←:上へ Esc:表示中のディレクトリに決定して戻る
function DirBrowse {
  $cur=$v['TARGET_DIR']
  if(-not $cur -or -not (Test-Path -LiteralPath $cur -PathType Container)){ $cur=(Get-Location).Path }
  $dsel=0; $off=0
  $lastEnd=[Console]::CursorTop
  while($true){
    $dirs=@(Get-ChildItem -LiteralPath $cur -Directory -ErrorAction SilentlyContinue)
    if($dsel -ge $dirs.Count -and $dirs.Count -gt 0){ $dsel=$dirs.Count-1 }
    [Console]::SetCursorPosition(0,0)
    Line '=================================================='
    Line '  対象ディレクトリ選択'
    Line '=================================================='
    Line ('  '+$cur)
    Line ''
    $h=[Console]::WindowHeight-10
    if($h -lt 1){ $h=1 }
    if($dsel -lt $off){ $off=$dsel }
    if($dsel -ge $off+$h){ $off=$dsel-$h+1 }
    if($dirs.Count -eq 0){ Line '  (サブディレクトリなし)' }
    for($i=$off; $i -lt [Math]::Min($off+$h,$dirs.Count); $i++){
      Line ('  '+$dirs[$i].Name) ($i -eq $dsel)
    }
    Line ''
    Line '  ↑↓:移動  →:このディレクトリに入る  ←:上の階層へ'
    Line '  Esc:このディレクトリに決定して戻る'
    Line '=================================================='
    $end=[Console]::CursorTop
    for($r=$end;$r -lt $lastEnd;$r++){ Line '' }
    $lastEnd=$end
    $k=[Console]::ReadKey($true)
    if($k.Key -eq 'Escape'){ Clear-Host; return $cur }
    elseif($k.Key -eq 'RightArrow' -and $dirs.Count -gt 0){ $cur=$dirs[$dsel].FullName; $dsel=0; $off=0 }
    elseif($k.Key -eq 'LeftArrow'){ $p=Split-Path -Parent $cur; if($p){ $cur=$p; $dsel=0; $off=0 } }
    elseif($k.Key -eq 'UpArrow' -and $dirs.Count -gt 0){ $dsel=($dsel+$dirs.Count-1)%$dirs.Count }
    elseif($k.Key -eq 'DownArrow' -and $dirs.Count -gt 0){ $dsel=($dsel+1)%$dirs.Count }
  }
}

function Run {
  Clear-Host
  [Console]::CursorVisible=$true
  foreach($n in $names){ Set-Item "env:$n" ($v[$n] -replace '"','') }
  if(-not $env:TARGET_PATTERN){ Write-Host '検索文字列が未入力です' }
  elseif(-not $env:TARGET_DIR -or -not (Test-Path -LiteralPath $env:TARGET_DIR -PathType Container)){ Write-Host ('ディレクトリの移動に失敗しました: '+$env:TARGET_DIR) }
  else {
    $env:PREVIEW_ONLY='1'
    & $psExe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $enc
    $rc=$LASTEXITCODE
    $env:PREVIEW_ONLY=''
    if($rc -eq 3){
      Write-Host ''
      Write-Host '上記ファイルを圧縮し、元ファイルを削除します。よろしいですか [Y,N]?' -NoNewline
      do { $c=[Console]::ReadKey($true).Key } until($c -eq 'Y' -or $c -eq 'N')
      Write-Host " $c"
      if($c -eq 'Y'){
        & $psExe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $enc
        if($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 2){ Write-Host '処理を中止しました。上記の内容を確認してください。' }
      } else { Write-Host 'キャンセルしました' }
    }
  }
  Write-Host ''
  Write-Host '何かキーを押すとメニューに戻ります...'
  [void][Console]::ReadKey($true)
  Clear-Host
  [Console]::CursorVisible=$false
}

Clear-Host
[Console]::CursorVisible=$false
while($true){
  Draw
  $k=[Console]::ReadKey($true)
  if($k.Key -eq 'UpArrow'){ $sel=($sel+5)%6 }
  elseif($k.Key -eq 'DownArrow' -or $k.Key -eq 'Tab'){ $sel=($sel+1)%6 }
  elseif($k.Key -eq 'Escape'){ break }
  elseif($k.Key -eq 'Enter'){
    if($sel -eq 5){ break }
    if($sel -eq 4){ Run }
    elseif($sel -eq 1){ $v['TARGET_DIR']=DirBrowse }
    else { $sel++ }
  }
  elseif($sel -lt 4){
    $n=$names[$sel]
    if($k.Key -eq 'Backspace'){ if($v[$n]){ $v[$n]=$v[$n].Substring(0,$v[$n].Length-1) } }
    elseif($k.Key -eq 'Delete'){ $v[$n]='' }
    elseif([int]$k.KeyChar -ge 32){ $v[$n]+=$k.KeyChar }
  }
}
[Console]::CursorVisible=$true
Clear-Host

#PS_START
$ErrorActionPreference='Stop'
$pattern=$env:TARGET_PATTERN
$zip=Join-Path (Get-Location) ('logs_'+$pattern+'.zip')
$tmp=$zip+'.partial.zip'
$inc=if($env:INCLUDE_EXTS){@($env:INCLUDE_EXTS -split ' ' | Where-Object{$_} | ForEach-Object{$_.ToLower()})}else{@()}
$exc=if($env:EXCLUDE_EXTS){@($env:EXCLUDE_EXTS -split ' ' | Where-Object{$_} | ForEach-Object{$_.ToLower()})}else{@()}
$files=@(Get-ChildItem -File | Where-Object{ $ext=$_.Extension.TrimStart('.').ToLower()
$_.Name.IndexOf($pattern,[StringComparison]::OrdinalIgnoreCase) -ge 0 -and ($inc.Count -eq 0 -or $inc -contains $ext) -and ($exc -notcontains $ext) -and ($_.FullName -ne $zip) -and ($_.FullName -ne $tmp) })
if($files.Count -eq 0){ Write-Host '対象ファイルが存在しません'
exit 2 }
Write-Host '対象ファイル:'
$files | ForEach-Object{ Write-Host ('  '+$_.Name+' ('+[Math]::Round($_.Length/1MB,2)+' MB)') }
if($env:PREVIEW_ONLY -eq '1'){ exit 3 }
if(Test-Path -LiteralPath $tmp){ Remove-Item -LiteralPath $tmp -Force }
$sevenZip=(Get-Command 7z.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
if(-not $sevenZip){ $candidates=@((Join-Path $env:ProgramFiles '7-Zip\7z.exe'))
if(${env:ProgramFiles(x86)}){ $candidates+=(Join-Path ${env:ProgramFiles(x86)} '7-Zip\7z.exe') }
$sevenZip=$candidates | Where-Object{Test-Path -LiteralPath $_} | Select-Object -First 1 }
$tar=(Get-Command tar.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
try { if($sevenZip){ Write-Host ('ZIP作成中（7-Zip / ZIP64対応）: '+[IO.Path]::GetFileName($zip))
$listFile=Join-Path $env:TEMP ('compress_'+[guid]::NewGuid().ToString('N')+'.txt')
try { [IO.File]::WriteAllLines($listFile,[string[]]$files.FullName,(New-Object System.Text.UTF8Encoding($false)))
& $sevenZip 'a' '-tzip' '-mx=5' '-y' ('-i@'+$listFile) $tmp | Out-Host } finally { Remove-Item -LiteralPath $listFile -Force -ErrorAction SilentlyContinue }
if($LASTEXITCODE -ne 0){ throw ('7-Zipが終了コード '+$LASTEXITCODE+' で失敗しました') }
& $sevenZip t $tmp | Out-Host
if($LASTEXITCODE -ne 0){ throw '作成したZIPの検証に失敗しました' } } elseif($tar){ Write-Host ('ZIP作成中（Windows tar / ZIP64対応）: '+[IO.Path]::GetFileName($zip))
$listFile=Join-Path $env:TEMP ('compress_'+[guid]::NewGuid().ToString('N')+'.txt')
try { [IO.File]::WriteAllLines($listFile,[string[]]$files.Name,[Text.Encoding]::Default)
& $tar '-a' '-c' '-f' $tmp '-T' $listFile } finally { Remove-Item -LiteralPath $listFile -Force -ErrorAction SilentlyContinue }
if($LASTEXITCODE -ne 0){ throw ('tarが終了コード '+$LASTEXITCODE+' で失敗しました') }
& $tar -tf $tmp | Out-Null
if($LASTEXITCODE -ne 0){ throw '作成したZIPの検証に失敗しました' } } else { $tooLarge=@($files | Where-Object{$_.Length -ge 2GB})
if($tooLarge.Count -gt 0){ throw ('2GB以上のファイルがあります。7-Zipをインストールするか、Windows標準のtar.exeが使える環境で実行してください: '+(($tooLarge | ForEach-Object{$_.Name}) -join ', ')) }
Write-Host ('ZIP作成中（Compress-Archive）: '+[IO.Path]::GetFileName($zip))
Compress-Archive -LiteralPath $files.FullName -DestinationPath $tmp -Force -ErrorAction Stop
}
if(-not (Test-Path -LiteralPath $tmp)){ throw 'ZIPファイルが作成されませんでした' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive=[IO.Compression.ZipFile]::OpenRead($tmp)
try { if($archive.Entries.Count -ne $files.Count){ throw ('ZIP内のファイル数が一致しません（予定 '+$files.Count+' / 実際 '+$archive.Entries.Count+'）') } } finally { $archive.Dispose() }
if((Get-Item -LiteralPath $tmp).Length -le 0){ throw '作成されたZIPファイルが空です' }
if(Test-Path -LiteralPath $zip){ $old=[IO.Compression.ZipFile]::OpenRead($zip)
$new=[IO.Compression.ZipFile]::Open($tmp,'Update')
try { foreach($e in $old.Entries){ if(-not $new.GetEntry($e.FullName)){ $src=$e.Open(); $dst=$new.CreateEntry($e.FullName).Open()
try { $src.CopyTo($dst) } finally { $dst.Dispose(); $src.Dispose() } } } } finally { $new.Dispose(); $old.Dispose() }
$bak=$zip+'.bak'
if(Test-Path -LiteralPath $bak){ Remove-Item -LiteralPath $bak -Force }
[IO.File]::Move($zip,$bak)
[IO.File]::Move($tmp,$zip)
Remove-Item -LiteralPath $bak -Force } else { [IO.File]::Move($tmp,$zip) } } catch { if(Test-Path -LiteralPath $tmp){ Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
Write-Host ('圧縮を中止しました: '+$_.Exception.Message)
Write-Host '元ファイルは削除していません'
exit 1 }
Write-Host 'ZIPの作成と検証に成功しました'
Write-Host '元ファイル削除中...'
$deleteErrors=@()
foreach($f in $files){ try { Remove-Item -LiteralPath $f.FullName -Force -ErrorAction Stop } catch { $deleteErrors+=$f.Name } }
if($deleteErrors.Count -gt 0){ Write-Host ('削除できなかった元ファイル: '+($deleteErrors -join ', '))
Write-Host ('ZIPは正常に作成済みです: '+$zip)
exit 4 }
Write-Host '完了しました'
Write-Host ('出力: '+$zip)
exit 0

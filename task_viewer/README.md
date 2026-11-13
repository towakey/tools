# task_viewer

Windows のタスクスケジューラに登録されているタスクを、IIS 上のブラウザ画面で一覧・検索するツール。
Python 3.7+ 標準モジュールのみで動作し、CGI は使わない（静的 HTML + データファイル）。

- `export_tasks.py` を SYSTEM 権限で定期実行し、タスク定義を `tasks.js` に書き出す
- `index.html` が `tasks.js` を読み込み、ブラウザ内で検索する
- フォルダを横断して、タスク名・説明・プログラム・引数（URL など）・開始フォルダ・作成者・実行ユーザーをキーワード検索できる
  （スペース区切りで AND 検索）。フォルダと有効/無効でも絞り込める

## ファイル構成

| ファイル | 役割 |
|---|---|
| `export_tasks.py` | タスク定義 (`%SystemRoot%\System32\Tasks` の XML) を読み取り `tasks.js` を出力 |
| `index.html` | 一覧・検索画面 |
| `setting.json` | 読み取り元・出力先・除外フォルダ・伏せ字パターン |
| `tasks.js` | 出力データ（自動生成） |
| `test_export_tasks.py` | セルフチェック (`python test_export_tasks.py`) |

## セットアップ

1. フォルダごと IIS の公開フォルダにコピーする（例: `C:\inetpub\wwwroot\task_viewer\`）。
   他のサーバーにも同じフォルダをコピーするだけでよい。サーバー名は自動で取得され、画面に表示される。
2. 管理者のコマンドプロンプトで、1時間ごとに実行するタスクを登録する（python.exe のパスは環境に合わせる）。

   ```bat
   schtasks /create /tn "TaskViewerExport" /sc hourly /ru SYSTEM ^
     /tr "\"C:\Python37\python.exe\" \"C:\inetpub\wwwroot\task_viewer\export_tasks.py\""
   schtasks /run /tn "TaskViewerExport"
   ```

   ※ `System32\Tasks` は管理者と SYSTEM しか読めないため、IIS（CGI）の権限では読み取れない。
   そのため、この方式で事前にデータを出力しておく。
3. ブラウザで `http://<サーバー>/task_viewer/index.html` を開く。
   すぐに最新状態にしたいときは `schtasks /run /tn "TaskViewerExport"` を実行する。

## setting.json

```jsonc
{
  "tasks_dir": "%SystemRoot%\\System32\\Tasks",   // タスク定義 XML の場所（環境変数を展開する）
  "output": "tasks.js",                          // 出力先（相対パスはこのフォルダ基準）
  "exclude_folders": ["\\Microsoft\\"],          // 出力しないフォルダ（前方一致、大文字小文字は区別しない）
  "mask_patterns": [                             // 引数のうち、一致した部分を *** に置き換える正規表現
    "(?i)(?<=password=)[^\\s\"&]+"
  ]
}
```

## 注意

- 引数にパスワードやトークンを直接書いているタスクがあると、そのまま画面に表示される。
  `mask_patterns` で伏せ字にするか、IIS 側でこのフォルダにアクセスできる人を制限すること。
- 前回/次回の実行時刻と前回の実行結果は、XML に含まれないため出力していない。
- 読み取れない XML があっても他のタスクは出力し、終了コード 1 で終わる（エラー内容は標準エラーに出力）。

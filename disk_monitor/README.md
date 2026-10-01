# disk_monitor

Windows Server 2019 / IIS / Python 3.7 CGI 環境向けのディスク使用量監視ツール。
標準モジュールのみで動作し、追加パッケージは不要。

- タスクスケジューラから `run_monitor.bat` を定期実行し、`setting.json` に設定した
  ドライブ・フォルダの使用量を `disk_usage.db` (SQLite) に蓄積
- 使用量が閾値を超えたら、ルールごとに設定したメールアドレスへアラート送信
  (同じ場所に複数の閾値・送信先を設定可能)
- `index.html` で任意期間の使用量推移を折れ線グラフ表示
  (アラート閾値の位置に水平線を表示)

## ファイル構成

| ファイル | 役割 |
|---|---|
| `disk_monitor.py` | 使用量取得・SQLite 保存・アラート送信 |
| `run_monitor.bat` | 実行用バッチ。`log\log_YYYYMMDDHHMMSS.log` に実行ログを出力 |
| `usage_data.py` | CGI。期間指定で使用量を JSON 返却 |
| `index.html` | 推移グラフ画面 (usage_data.py を fetch して描画) |
| `setting.json` | 監視対象・閾値・送信先・SMTP 設定 |
| `log/` | 実行ログ (bat が自動作成、30 日で自動削除) |

## セットアップ

### 1. 配置

例: `C:\inetpub\wwwroot\disk_monitor\` に配置。

### 2. IIS CGI の有効化

1. サーバーマネージャーで「アプリケーション開発」→「CGI」をインストール
2. IIS マネージャー → 対象サイト → 「ハンドラー マッピング」→「スクリプト マップの追加」
   - 要求パス: `*.py`
   - 実行可能ファイル: `"C:\Python37\python.exe" -u "%s" "%s"` (python.exe のパスは環境に合わせる)
   - 名前: `PythonCGI`
3. サーバーレベルの「ISAPI および CGI 制限」に `C:\Python37\python.exe` を「許可」で追加
4. `IIS_IUSRS` (またはアプリケーションプール ID) に以下の権限を付与
   - `setting.json`, `usage_data.py`: 読み取り
   - `disk_usage.db` と配置フォルダ: 読み取り + 書き込み

### 3. タスクスケジューラ登録 (30 分おき)

管理者権限のコマンドプロンプト:

```bat
schtasks /create /tn "DiskMonitor" /sc minute /mo 30 ^
  /tr "C:\inetpub\wwwroot\disk_monitor\run_monitor.bat" /ru SYSTEM
```

GUI から作成する場合は「操作」に `run_monitor.bat`、「開始」に配置フォルダを指定する。
ログは配置フォルダの `log\log_YYYYMMDDHHMMSS.log` に出力される。

## setting.json

```jsonc
{
  "database": "disk_usage.db",      // SQLite ファイル (相対パスは配置フォルダ基準)
  "alert_resend_minutes": 1440,     // 超過継続中の再送間隔(分)。0 で新規超過時のみ送信
  "smtp": {
    "host": "...", "port": 587,
    "use_tls": true,                // STARTTLS
    "use_ssl": false,               // SMTPS(465) を使う場合は true
    "username": "...", "password": "...",
    "from": "disk-monitor@example.co.jp",
    "timeout_seconds": 10
  },
  "targets": [
    {
      "id": "d_drive",              // 任意の一意 ID (グラフ・ルール管理に使用)
      "name": "Dドライブ",
      "type": "drive",              // drive: ドライブ全体 / folder: フォルダの合計サイズ
      "path": "D:\\",
      "alerts": [
        // 1つの対象に複数ルールを設定でき、それぞれ送信先を変えられる
        { "label": "警告 80%", "threshold_percent": 80, "emails": ["admin@example.co.jp"] },
        { "label": "重大 90%", "threshold_percent": 90, "emails": ["admin@example.co.jp", "manager@example.co.jp"] }
      ]
    },
    {
      "id": "backup_dir",
      "name": "バックアップフォルダ",
      "type": "folder",
      "path": "D:\\backup",
      "alerts": [
        { "label": "100GB 超", "threshold_gb": 100, "emails": ["backup@example.co.jp"] }
      ]
    }
  ]
}
```

- `threshold_percent`: ボリューム総容量に対する使用率 (%)。`drive` ではドライブ使用率、
  `folder` では「フォルダサイズ ÷ 所属ボリューム容量」
- `threshold_gb`: 使用量 (GB)。どちらか一方を指定
- `emails`: 記載したすべてのアドレスに送信される

## グラフ画面

ブラウザで `http://<サーバー>/disk_monitor/index.html` を開く。
期間・表示対象・単位 (GB / %) を切り替えられる。
破線はアラート閾値 (設定が無い対象には表示されない)。

## 動作メモ

- フォルダ測定は再帰走査のため、巨大フォルダでは時間がかかる
- 測定結果はローカル時刻 (`YYYY-MM-DD HH:MM:SS`) で保存
- メール送信失敗・対象パス不存在などのエラーは他対象の処理を止めず、
  実行ログに記録され終了コード 1 で終わる

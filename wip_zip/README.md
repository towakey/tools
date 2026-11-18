# wip_zip

`\\10.20.24.88\load4` 配下の `wip_stat.YYYYMMDD` ファイルを期間指定で集めて、1つのZIPにまとめるツール。

## 使い方

```
wip_zip.bat [開始日YYYYMMDD] [終了日YYYYMMDD]
```

- 引数省略時: `setting.json` の `start_date` / `end_date`（既定: 20240101〜昨日）
- `end_date` には `yesterday` / `today` も指定可能
- 例: `wip_zip.bat 20250101 20250630`

## 必要なもの

- 7-Zip（`7z.exe`）。PATH に無い場合は `setting.json` の `seven_zip` にフルパスを書く
- PowerShell（Windows 標準でOK）

## setting.json

| キー | 説明 |
|---|---|
| `root_folder` | 保存ルート (`\\10.20.24.88\load4`) |
| `file_prefix` | 対象ファイル名のプレフィックス (`wip_stat`) |
| `start_date` / `end_date` | 既定の期間。`YYYYMMDD` or `yesterday`/`today` |
| `output_dir` | ZIP出力先。相対パスはBATのフォルダ基準 |
| `zip_name` | ZIP名。`{start}`/`{end}` が期間に置き換わる |
| `seven_zip` | 7z.exe のパス。PATH が通ってれば `7z` のまま |
| `scan_dirs` | 検索対象。`path`=root_folder からの相対パス（空=ルート直下）、`recursive`=サブフォルダも検索 |

### scan_dirs の仕組み

拡張子が日付(`YYYYMMDD`)なので、フォルダ階層を意識せず「どこにあるか」だけ指定する。

- `stock_data` を `recursive: true` → `stock_data\2024\01` 等の年月階層を全部探す
- `""`（ルート）を `recursive: false` → ルート直下のみ探す（2025年以降のファイル用）

**2025年のファイルが将来 `stock_data` に移動しても設定変更不要**（再帰検索で見つかる）。ルート直下の検索をやめたい場合は `""` のエントリを消す。

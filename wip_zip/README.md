# wip_zip

`\\10.20.24.88\load4` 配下の `wip_stat.YYYYMMDD` ファイルを期間指定で集めて、1つのZIPにまとめるバッチ。`wip_zip.bat` 1つだけで動く（PowerShellを内蔵）。

## 使い方

```
wip_zip.bat [開始日YYYYMMDD] [終了日YYYYMMDD]
```

- 引数省略時: bat先頭の設定 `CFG_START` / `CFG_END`（既定: 20240101〜昨日）
- `CFG_END` には `yesterday` / `today` も指定可能
- 例: `wip_zip.bat 20250101 20250630`

## 必要なもの

- 7-Zip（`7z.exe`）。PATH に無い場合は設定 `CFG_7Z` にフルパスを書く
- PowerShell（Windows 標準でOK）

## 設定（`wip_zip.bat` 先頭の `set "CFG_*"` を編集）

| 変数 | 説明 |
|---|---|
| `CFG_ROOT` | 保存ルート (`\\10.20.24.88\load4`) |
| `CFG_PREFIX` | 対象ファイル名のプレフィックス (`wip_stat`) |
| `CFG_START` / `CFG_END` | 既定の期間。`YYYYMMDD` or `yesterday`/`today` |
| `CFG_OUTDIR` | ZIP出力先。相対パスはbatのフォルダ基準 |
| `CFG_ZIPNAME` | ZIP名。`{start}`/`{end}` が期間に置き換わる |
| `CFG_7Z` | 7z.exe のパス。PATH が通ってれば `7z` のまま |
| `CFG_DIRS` | 検索対象。`相対パス:recursive` を `;` 区切りで列挙 |

### CFG_DIRS の仕組み

拡張子が日付(`YYYYMMDD`)なので、フォルダ階層を意識せず「どこにあるか」だけ指定する。

- `stock_data:true` → `stock_data\2024\01` 等の年月階層を全部探す
- `:false`（相対パス空）→ ルート直下のみ探す（2025年以降のファイル用）

**2025年のファイルが将来 `stock_data` に移動しても設定変更不要**（再帰検索で見つかる）。ルート直下の検索をやめたい場合は `:false` のエントリを消す。

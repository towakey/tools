#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
usage_data.py (IIS CGI)

SQLite に蓄積した使用量を JSON で返す。
index.html から fetch される。

パラメータ:
    from    : YYYY-MM-DD (省略時: to の7日前)
    to      : YYYY-MM-DD (省略時: 今日。当日 23:59:59 まで含む)
    targets : target_id をカンマ区切り (省略時: すべて)
"""
import os
import sys
import json
import sqlite3
import cgi
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTING_PATH = os.path.join(BASE_DIR, "setting.json")


def _emit(obj):
    sys.stdout.write("Content-Type: application/json; charset=utf-8\r\n\r\n")
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))


def _load_targets():
    """setting.json から対象一覧とアラート閾値を返す(メールアドレスは外す)。"""
    try:
        with open(SETTING_PATH, "r", encoding="utf-8-sig") as f:
            settings = json.load(f)
    except Exception:
        return []
    out = []
    for t in settings.get("targets", []):
        out.append({
            "id": t.get("id", t.get("path", "")),
            "name": t.get("name", t.get("id", "")),
            "path": t.get("path", ""),
            "type": t.get("type", "drive"),
            "alerts": [
                {"label": a.get("label", ""),
                 "threshold_gb": a.get("threshold_gb"),
                 "threshold_percent": a.get("threshold_percent")}
                for a in t.get("alerts", [])
                if "threshold_gb" in a or "threshold_percent" in a
            ],
        })
    return out


def main():
    fs = cgi.FieldStorage()
    frm = fs.getfirst("from", "")
    to = fs.getfirst("to", "")
    targets_param = fs.getfirst("targets", "").strip()

    today = datetime.now().date()
    try:
        to_date = datetime.strptime(to, "%Y-%m-%d").date() if to else today
    except ValueError:
        to_date = today
    try:
        from_date = datetime.strptime(frm, "%Y-%m-%d").date() if frm \
            else to_date - timedelta(days=7)
    except ValueError:
        from_date = to_date - timedelta(days=7)

    ts_from = from_date.strftime("%Y-%m-%d 00:00:00")
    ts_to = to_date.strftime("%Y-%m-%d 23:59:59")

    targets = _load_targets()
    records = []
    db_path = os.path.join(BASE_DIR, "disk_usage.db")
    if os.path.exists(db_path):
        conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        try:
            sql = ("SELECT ts, target_id, used_bytes, total_bytes"
                   " FROM usage_records WHERE ts BETWEEN ? AND ?")
            params = [ts_from, ts_to]
            if targets_param:
                ids = [s for s in targets_param.split(",") if s]
                sql += " AND target_id IN (%s)" % ",".join("?" * len(ids))
                params += ids
            sql += " ORDER BY ts"
            for ts, tid, used, total in conn.execute(sql, params):
                records.append({"ts": ts, "target_id": tid,
                                "used_bytes": used, "total_bytes": total})
        finally:
            conn.close()

    _emit({"ok": True, "from": str(from_date), "to": str(to_date),
           "targets": targets, "records": records})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _emit({"ok": False, "error": str(e)})

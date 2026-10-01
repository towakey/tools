#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
disk_monitor.py

Windows Server 2019 / Python 3.7+ 標準モジュールのみで動作。
setting.json に定義したドライブ・フォルダの使用量を取得して SQLite に保存し、
設定した閾値を超えた場合にアラートメールを送信する。

run_monitor.bat 経由でタスクスケジューラから定期実行することを想定。
手動実行:
    python disk_monitor.py
    python disk_monitor.py --setting setting.json
"""
import os
import sys
import json
import sqlite3
import smtplib
import argparse
import traceback
import shutil
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formatdate

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SETTING = os.path.join(BASE_DIR, "setting.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    target_id TEXT NOT NULL,
    name TEXT,
    path TEXT,
    used_bytes INTEGER NOT NULL,
    total_bytes INTEGER,
    free_bytes INTEGER
);
CREATE INDEX IF NOT EXISTS idx_usage_records_target_ts
    ON usage_records (target_id, ts);
CREATE TABLE IF NOT EXISTS alert_state (
    rule_key TEXT PRIMARY KEY,
    exceeded INTEGER NOT NULL DEFAULT 0,
    last_alert_ts TEXT
);
"""


def load_settings(path):
    # utf-8-sig で BOM 付き JSON にも対応
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def folder_size(path):
    """フォルダ以下の合計サイズ(バイト)。シンボリックリンクと読めないファイルはスキップ。"""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                if os.path.islink(fp):
                    continue
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def measure_target(target):
    """target の使用量を測定し (used_bytes, total_bytes, free_bytes) を返す。

    drive : shutil.disk_usage の使用済み/総容量/空き。
    folder: フォルダの再帰合計サイズを used とし、total/free は
            そのフォルダが属するボリュームの容量を使う。
    """
    path = target["path"]
    if not os.path.exists(path):
        raise OSError("path does not exist: %s" % path)

    ttype = target.get("type", "drive")
    du = shutil.disk_usage(path)
    if ttype == "folder":
        used = folder_size(path)
    else:
        used = du.used
    return used, du.total, du.free


def send_mail(smtp, recipients, subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    from_addr = smtp.get("from", "disk-monitor@localhost")
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)

    timeout = int(smtp.get("timeout_seconds", 10))
    if smtp.get("use_ssl"):
        conn = smtplib.SMTP_SSL(smtp["host"], int(smtp.get("port", 465)),
                                timeout=timeout)
    else:
        conn = smtplib.SMTP(smtp["host"], int(smtp.get("port", 25)),
                            timeout=timeout)
    try:
        if smtp.get("use_tls") and not smtp.get("use_ssl"):
            conn.starttls()
        if smtp.get("username"):
            conn.login(smtp["username"], smtp.get("password", ""))
        conn.sendmail(from_addr, recipients, msg.as_string())
    finally:
        try:
            conn.quit()
        except Exception:
            pass


def rule_limit_bytes(rule, total_bytes):
    """ルールの閾値をバイトに変換。threshold_gb or threshold_percent。"""
    if "threshold_gb" in rule:
        return int(float(rule["threshold_gb"]) * 1024 ** 3)
    if "threshold_percent" in rule and total_bytes:
        return int(total_bytes * float(rule["threshold_percent"]) / 100.0)
    return None


def check_alerts(conn, settings, target, used_bytes, total_bytes, ts):
    """閾値超過ルールを評価し、必要に応じてメール送信。エラー数を返す。"""
    errors = 0
    resend_min = int(settings.get("alert_resend_minutes", 1440))
    smtp = settings.get("smtp", {})
    tname = target.get("name") or target.get("id")
    now = datetime.now()

    for i, rule in enumerate(target.get("alerts", [])):
        limit = rule_limit_bytes(rule, total_bytes)
        recipients = rule.get("emails") or []
        if limit is None or not recipients:
            continue

        exceeded = used_bytes >= limit
        rule_key = "%s#%d" % (target.get("id", target["path"]), i)
        row = conn.execute(
            "SELECT exceeded, last_alert_ts FROM alert_state WHERE rule_key = ?",
            (rule_key,)).fetchone()
        prev_exceeded = bool(row[0]) if row else False
        last_alert_ts = row[1] if row else None

        send = False
        if exceeded:
            if not prev_exceeded or not last_alert_ts:
                send = True
            elif resend_min > 0:
                last = datetime.strptime(last_alert_ts, "%Y-%m-%d %H:%M:%S")
                send = now - last >= timedelta(minutes=resend_min)

        if send:
            label = rule.get("label", "")
            used_gb = used_bytes / 1024.0 ** 3
            limit_gb = limit / 1024.0 ** 3
            pct = (used_bytes * 100.0 / total_bytes) if total_bytes else 0
            subject = "[DiskMonitor] ALERT %s (%s %.1fGB >= %.1fGB)" % (
                tname, label, used_gb, limit_gb)
            body = (
                "ディスク使用量アラート\n\n"
                "対象: %s\n"
                "パス: %s\n"
                "ルール: %s\n"
                "現在の使用量: %.1f GB (ボリューム使用率 %.1f%%)\n"
                "閾値: %.1f GB\n"
                "ボリューム容量: %.1f GB / 空き %.1f GB\n"
                "検知時刻: %s\n"
            ) % (
                tname, target["path"], label or rule_key,
                used_gb, pct, limit_gb,
                total_bytes / 1024.0 ** 3 if total_bytes else 0,
                (total_bytes - used_bytes) / 1024.0 ** 3 if total_bytes else 0,
                ts)
            try:
                send_mail(smtp, recipients, subject, body)
                print("  ALERT SENT %s -> %s" % (rule_key, ", ".join(recipients)))
                last_alert_ts = ts
            except Exception:
                errors += 1
                print("  MAIL ERROR %s" % rule_key)
                traceback.print_exc()

        conn.execute(
            "INSERT OR REPLACE INTO alert_state (rule_key, exceeded, last_alert_ts)"
            " VALUES (?, ?, ?)",
            (rule_key, 1 if exceeded else 0, last_alert_ts))
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setting", default=DEFAULT_SETTING)
    args = ap.parse_args()

    print("===== disk_monitor %s =====" % now_str())
    try:
        settings = load_settings(args.setting)
    except Exception:
        print("FATAL: cannot load setting file: %s" % args.setting)
        traceback.print_exc()
        return 2

    db_path = settings.get("database", "disk_usage.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(BASE_DIR, db_path)

    errors = 0
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        ts = now_str()
        for target in settings.get("targets", []):
            tid = target.get("id", target.get("path", "?"))
            try:
                used, total, free = measure_target(target)
                conn.execute(
                    "INSERT INTO usage_records"
                    " (ts, target_id, name, path, used_bytes, total_bytes, free_bytes)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ts, tid, target.get("name"), target["path"],
                     used, total, free))
                print("%s %-16s used=%.2fGB total=%.1fGB" % (
                    ts, tid, used / 1024.0 ** 3, total / 1024.0 ** 3))
                errors += check_alerts(conn, settings, target, used, total, ts)
            except Exception:
                errors += 1
                print("ERROR target %s" % tid)
                traceback.print_exc()
        conn.commit()
    finally:
        conn.close()

    print("===== done errors=%d =====" % errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

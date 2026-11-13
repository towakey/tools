#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_tasks.py

タスクスケジューラの定義 (setting.json の tasks_dir 配下の XML) を読み取り、
index.html から読み込む tasks.js を出力する。Python 3.7+ 標準モジュールのみ。
Tasks フォルダは管理者/SYSTEM しか読めないため、タスクスケジューラから SYSTEM で実行する。

    python export_tasks.py
    python export_tasks.py --setting setting.json
"""
import os
import re
import sys
import json
import socket
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NS = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
WELL_KNOWN_SIDS = {"S-1-5-18": "SYSTEM", "S-1-5-19": "LOCAL SERVICE", "S-1-5-20": "NETWORK SERVICE"}
TRIGGERS = {
    "TimeTrigger": "1回", "BootTrigger": "起動時", "LogonTrigger": "ログオン時",
    "IdleTrigger": "アイドル時", "EventTrigger": "イベント時", "RegistrationTrigger": "登録時",
    "SessionStateChangeTrigger": "セッション状態変更時",
}
SCHEDULES = {"ScheduleByDay": "毎日", "ScheduleByWeek": "毎週",
             "ScheduleByMonth": "毎月", "ScheduleByMonthDayOfWeek": "毎月(曜日指定)"}
DAYS = {"Sunday": "日", "Monday": "月", "Tuesday": "火", "Wednesday": "水",
        "Thursday": "木", "Friday": "金", "Saturday": "土"}


def duration(iso):
    """PT1H30M -> 1時間30分 (変換できなければそのまま)"""
    m = re.match(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$", iso)
    if not m or not any(m.groups()):
        return iso
    return "".join(v + u for v, u in zip(m.groups(), ("日", "時間", "分", "秒")) if v)


def text(el, path):
    if el is None:
        return ""
    found = el.find("/".join(NS + p for p in path.split("/")))
    return (found.text or "").strip() if found is not None else ""


def trigger_summary(trig):
    tag = trig.tag.replace(NS, "")
    label = TRIGGERS.get(tag, tag)
    if tag == "CalendarTrigger":
        label = "?"
        for child in trig:
            name = child.tag.replace(NS, "")
            if name in SCHEDULES:
                label = SCHEDULES[name]
                days = child.find(NS + "DaysOfWeek")
                if days is not None:
                    label += "(" + "".join(DAYS.get(d.tag.replace(NS, ""), "") for d in days) + ")"
    parts = [label]
    start = text(trig, "StartBoundary")
    if start:
        parts.append(start.replace("T", " ")[:16])
    interval = text(trig, "Repetition/Interval")
    if interval:
        parts.append(duration(interval) + "ごと")
    if text(trig, "Enabled").lower() == "false":
        parts.append("(無効)")
    return " ".join(parts)


def action_summary(act):
    tag = act.tag.replace(NS, "")
    if tag == "Exec":
        return {"type": "プログラム", "command": text(act, "Command"),
                "arguments": text(act, "Arguments"), "workdir": text(act, "WorkingDirectory")}
    if tag == "ComHandler":
        return {"type": "COM", "command": text(act, "ClassId"), "arguments": text(act, "Data"), "workdir": ""}
    return {"type": tag, "command": text(act, "Subject") or text(act, "Title"),
            "arguments": text(act, "Body"), "workdir": ""}


def parse_task(path, folder, name, masks):
    root = ET.parse(path).getroot()
    principal = root.find(NS + "Principals/" + NS + "Principal")
    user = text(principal, "UserId") or text(principal, "GroupId")
    triggers = root.find(NS + "Triggers")
    actions = root.find(NS + "Actions")
    acts = [action_summary(a) for a in (actions if actions is not None else [])]
    for a in acts:
        for m in masks:
            a["arguments"] = m.sub("***", a["arguments"])
    return {
        "folder": folder,
        "name": name,
        "description": text(root, "RegistrationInfo/Description"),
        "author": text(root, "RegistrationInfo/Author"),
        "user": WELL_KNOWN_SIDS.get(user, user),
        "enabled": text(root, "Settings/Enabled").lower() != "false",
        "triggers": [trigger_summary(t) for t in (triggers if triggers is not None else [])],
        "actions": acts,
    }


def collect(tasks_dir, exclude_folders, masks):
    tasks, errors = [], []
    excludes = [e.lower() for e in exclude_folders]
    for dirpath, dirnames, filenames in os.walk(tasks_dir):
        rel = os.path.relpath(dirpath, tasks_dir)
        folder = "\\" if rel == "." else "\\" + rel.replace("/", "\\") + "\\"
        if any(folder.lower().startswith(e) for e in excludes):
            dirnames[:] = []
            continue
        dirnames.sort()
        for fn in sorted(filenames):
            try:
                tasks.append(parse_task(os.path.join(dirpath, fn), folder, fn, masks))
            except (ET.ParseError, OSError) as e:
                errors.append("{}{}: {}".format(folder, fn, e))
    return tasks, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setting", default=os.path.join(BASE_DIR, "setting.json"))
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="replace")
    with open(args.setting, "r", encoding="utf-8") as f:
        setting = json.load(f)

    tasks_dir = os.path.expandvars(setting.get("tasks_dir", r"%SystemRoot%\System32\Tasks"))
    if not os.path.isdir(tasks_dir):
        sys.exit("tasks_dir が見つかりません: " + tasks_dir)
    masks = [re.compile(p) for p in setting.get("mask_patterns", [])]
    tasks, errors = collect(tasks_dir, setting.get("exclude_folders", []), masks)

    data = {
        "server": socket.gethostname(),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tasks": tasks,
    }
    out = os.path.join(BASE_DIR, setting.get("output", "tasks.js"))
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("window.TASK_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n")
    os.replace(tmp, out)

    print("{} 件を出力しました: {}".format(len(tasks), out))
    for e in errors:
        print("読み取り失敗: " + e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

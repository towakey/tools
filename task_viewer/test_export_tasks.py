# -*- coding: utf-8 -*-
"""python test_export_tasks.py で実行する簡易セルフチェック。"""
import os
import re
import tempfile
import export_tasks as ex

XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>売上集計</Description></RegistrationInfo>
  <Principals><Principal id="Author"><UserId>S-1-5-18</UserId></Principal></Principals>
  <Settings><Enabled>false</Enabled></Settings>
  <Triggers><CalendarTrigger><StartBoundary>2026-01-01T03:00:00</StartBoundary>
    <Repetition><Interval>PT1H30M</Interval></Repetition>
    <ScheduleByWeek><DaysOfWeek><Monday /><Friday /></DaysOfWeek></ScheduleByWeek>
  </CalendarTrigger></Triggers>
  <Actions><Exec><Command>python.exe</Command><Arguments>a.py http://x/?password=abc&amp;b=1</Arguments></Exec></Actions>
</Task>
"""

with tempfile.TemporaryDirectory() as d:
    for sub in ("業務", "Microsoft"):
        os.makedirs(os.path.join(d, sub))
        with open(os.path.join(d, sub, "集計"), "w", encoding="utf-16") as f:
            f.write(XML)
    with open(os.path.join(d, "broken"), "w") as f:
        f.write("not xml")
    tasks, errors = ex.collect(d, ["\\Microsoft\\"], [re.compile(r"(?i)(?<=password=)[^\s\"&]+")])

assert len(tasks) == 1 and len(errors) == 1, (tasks, errors)
t = tasks[0]
assert t["folder"] == "\\業務\\" and t["name"] == "集計"
assert t["description"] == "売上集計" and t["user"] == "SYSTEM" and t["enabled"] is False
assert t["triggers"] == ["毎週(月金) 2026-01-01 03:00 1時間30分ごと"], t["triggers"]
assert t["actions"][0]["arguments"] == "a.py http://x/?password=***&b=1", t["actions"]
print("OK")

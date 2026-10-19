#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调度器逻辑单测: 档期判断/防重标记/档期配置"""
import datetime
import json
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import scheduler

BJT = scheduler.BJT
passed = []


def check(name, cond):
    passed.append((name, bool(cond)))
    print(("  ✅ " if cond else "  ❌ ") + name)


def at_bjt(h, m):
    return datetime.datetime(2026, 10, 19, h, m, tzinfo=BJT)


# ① 档期判断
check("08:29 AGI 未到期", not scheduler.period_due("agi", at_bjt(8, 29)))
check("08:30 AGI 到期", scheduler.period_due("agi", at_bjt(8, 30)))
check("11:59 AI 未到期", not scheduler.period_due("ai", at_bjt(11, 59)))
check("12:00 AI 到期", scheduler.period_due("ai", at_bjt(12, 0)))
check("20:00 AGI 到期", scheduler.period_due("agi", at_bjt(20, 0)))

# ② 防重: 临时 state
tmp = tempfile.mkdtemp()
old_state = scheduler.STATE
scheduler.STATE = os.path.join(tmp, "state.json")

st = {}
with open(scheduler.STATE, "w") as f:
    json.dump({"weibo_agi_run_date": "2026-10-19",
               "weibo_ai_last_date": "2026-10-19"}, f)
check("AGI 今日已运行 → done", scheduler.already_done("agi", at_bjt(9, 0)))
check("AI 今日已发布 → done", scheduler.already_done("ai", at_bjt(13, 0)))

with open(scheduler.STATE, "w") as f:
    json.dump({"weibo_agi_run_date": "2026-10-18"}, f)
check("AGI 昨日运行 → 未 done", not scheduler.already_done("agi", at_bjt(9, 0)))

# ③ mark_done 写回
scheduler.mark_done("agi")
st = json.load(open(scheduler.STATE))
check("mark_done(agi) 写 run_date", st.get("weibo_agi_run_date") ==
      datetime.datetime.now(BJT).strftime("%Y-%m-%d"))

# ④ 档期配置读取
cfg_tmp = os.path.join(tmp, "config.json")
with open(cfg_tmp, "w") as f:
    json.dump({"weibo_post": {"agi_enabled": False, "ai_enabled": True}}, f)
old_cfg = scheduler.CONFIG
scheduler.CONFIG = cfg_tmp
check("agi 关 ai 开 → ('ai',)", scheduler.active_periods() == ("ai",))
scheduler.CONFIG = old_cfg
scheduler.STATE = old_state

n_fail = sum(1 for _, ok in passed if not ok)
print(f"\n{'='*40}\n调度器逻辑: {len(passed)-n_fail}/{len(passed)} 通过")
sys.exit(1 if n_fail else 0)

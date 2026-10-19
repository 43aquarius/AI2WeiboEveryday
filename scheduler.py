# -*- coding: utf-8 -*-
"""微博常驻定时调度器(容器环境无 cron, 用本进程替代)

时间表(北京时间, config.json weibo_post.*_enabled 控制):
  - agi_enabled  : 每日 08:30 → AGI 日报  (UTC 00:30)
  - ai_enabled   : 每日 12:00 → AI 情报站 (UTC 04:00)
    agi_daily 自带期号防重(无新期跳过); ai_news 自带当日防重。

自愈能力(继承小黑盒 scheduler v2 思路):
  - 失败重试: 档期任务失败后每 30 分钟重试, 单档期每周期最多 3 次
  - 日志轮转: scheduler.log 超 5MB 清空

用法:
  nohup python3 scheduler.py >/dev/null 2>&1 &
日志: scheduler.log (同目录)
"""
import datetime
import json
import os
import subprocess
import sys
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "scheduler.log")
STATE = os.path.join(BASE, "state.json")
CONFIG = os.path.join(BASE, "config.json")
MAX_LOG_BYTES = 5 * 1024 * 1024

BJT = datetime.timezone(datetime.timedelta(hours=8))  # 北京时间

AGI_SLOT = (8, 30)        # 每日 08:30 (北京时间), 比小黑盒早1小时错峰
AI_SLOT = (12, 0)         # 每日 12:00 (北京时间)
RETRY_INTERVAL = 30 * 60  # 失败重试间隔(秒)
MAX_RETRY = 3             # 每档期每周期最多重试次数

PERIODS = {
    "agi": {"slot": AGI_SLOT, "script": "agi_daily.py", "daily": True},
    "ai": {"slot": AI_SLOT, "script": "ai_news.py", "daily": True},
}


def log(msg: str):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > MAX_LOG_BYTES:
            with open(LOG, "w") as f:
                f.write("")
        with open(LOG, "a") as f:
            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"{msg}\n")
    except OSError:
        pass


def beijing_now() -> datetime.datetime:
    return datetime.datetime.now(BJT)


def active_periods() -> tuple:
    try:
        with open(CONFIG) as f:
            cfg = json.load(f)
        wp = cfg.get("weibo_post", {})
        out = []
        if wp.get("agi_enabled", True):
            out.append("agi")
        if wp.get("ai_enabled", True):
            out.append("ai")
        return tuple(out) if out else ("agi", "ai")
    except (OSError, ValueError):
        return ("agi", "ai")


def load_marks() -> dict:
    if os.path.exists(STATE):
        try:
            with open(STATE) as f:
                return json.load(f)
        except ValueError:
            return {}
    return {}


def already_done(period: str, now_bjt: datetime.datetime) -> bool:
    """该档期本周期是否已完成(state 标记 + 逻辑防重兜底)

    agi: weibo_agi_last_issue 是期号, 但"最新期是否已发"由 agi_daily
    内部判断; 这里只看"今天有没有成功跑过"标记(成功/跳过都算)。
    ai:  weibo_ai_last_date == 今天 即完成。
    """
    st = load_marks()
    today = now_bjt.strftime("%Y-%m-%d")
    if period == "agi":
        return st.get("weibo_agi_run_date") == today
    if period == "ai":
        return st.get("weibo_ai_last_date") == today
    return False


def mark_done(period: str):
    st = load_marks()
    if period == "agi":
        st["weibo_agi_run_date"] = beijing_now().strftime("%Y-%m-%d")
    with open(STATE, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def period_due(period: str, now_bjt: datetime.datetime) -> bool:
    """档期时间已到(且本周期未完成)"""
    conf = PERIODS[period]
    hh, mm = conf["slot"]
    slot_dt = now_bjt.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return now_bjt >= slot_dt


def run_period(period: str) -> bool:
    """执行档期脚本; 返回 True=成功或正常跳过, False=失败(需重试)"""
    script = PERIODS[period]["script"]
    log(f"[{period}] 开始执行 {script}")
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(BASE, script)],
            capture_output=True, text=True, timeout=1800, cwd=BASE)
        ok = r.returncode == 0
        tail = (r.stdout or "").strip().split("\n")[-3:]
        log(f"[{period}] {'✅ 完成' if ok else '❌ 失败'} "
            f"(rc={r.returncode}) | " + " / ".join(tail)[:400])
        if r.returncode != 0:
            log(f"[{period}] stderr: {(r.stderr or '')[-600:]}")
        return ok
    except subprocess.TimeoutExpired:
        log(f"[{period}] ❌ 超时(30分钟)")
        return False
    except Exception:
        log(f"[{period}] ❌ 异常: {traceback.format_exc()[-400:]}")
        return False


def main():
    periods = active_periods()
    log(f"调度器启动, 档期: {periods}, 北京时间 {beijing_now():%Y-%m-%d %H:%M}")
    print(f"[scheduler] 启动, 档期 {periods}")
    fails = {p: 0 for p in periods}     # 本周期失败计数

    while True:
        now = beijing_now()
        for p in periods:
            if already_done(p, now):
                continue
            if not period_due(p, now):
                continue
            ok = run_period(p)
            if ok:
                mark_done(p)
                fails[p] = 0
            else:
                fails[p] += 1
                if fails[p] >= MAX_RETRY:
                    log(f"[{p}] 连续失败 {fails[p]} 次, 本周期放弃, 明天再试")
                    mark_done(p)      # 防止无限重试
                    fails[p] = 0
                else:
                    log(f"[{p}] 第 {fails[p]} 次失败, {RETRY_INTERVAL//60} "
                        f"分钟后重试")
        time.sleep(60)


if __name__ == "__main__":
    main()

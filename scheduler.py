# -*- coding: utf-8 -*-
"""微博五栏目矩阵 · 常驻调度器(2026-10-22 转型版)

时间表(北京时间, config.json matrix.{col}_enabled 控制):
  morning  07:30  早安 · AI壁纸      col_morning.py
  yiyan    12:00  一言 · 午间签      col_yiyan.py
  pet      15:00  萌宠 · 午后图签    col_pet.py
  history  18:30  历史 · 上的今天    col_history.py
  hot      21:30  热榜 · 晚间聚合    col_hot.py

自愈能力:
  - 启动补发: 档期已过而 state 无记录(环境重启state丢失场景)时,
    与"我的微博"对账——当日已有对应话题帖则补写标记防重发, 否则补发
  - 失败重试: 档期失败后每 30 分钟重试, 单档期每日最多 3 次
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

BJT = datetime.timezone(datetime.timedelta(hours=8))

RETRY_INTERVAL = 30 * 60
MAX_RETRY = 3

COLUMNS = {
    "morning": {"slot": (7, 30), "script": "col_morning.py", "tag": "#早安#"},
    "yiyan": {"slot": (12, 0), "script": "col_yiyan.py", "tag": "#一言#"},
    "pet": {"slot": (15, 0), "script": "col_pet.py", "tag": "#萌宠#"},
    "history": {"slot": (18, 30), "script": "col_history.py",
                "tag": "#历史上的今天#"},
    "hot": {"slot": (21, 30), "script": "col_hot.py", "tag": "#今日热榜#"},
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


def load_state() -> dict:
    if os.path.exists(STATE):
        try:
            with open(STATE) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}


def save_state(st: dict):
    with open(STATE, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def active_columns() -> tuple:
    try:
        from matrix_common import load_config
        mx = load_config().get("matrix", {})
        out = [c for c in COLUMNS if mx.get(f"{c}_enabled", True)]
        return tuple(out) if out else tuple(COLUMNS)
    except (OSError, ValueError, ImportError):
        return tuple(COLUMNS)


def column_done(col: str, now_bjt=None) -> bool:
    today = (now_bjt or beijing_now()).strftime("%Y-%m-%d")
    return load_state().get(f"matrix_{col}_last_date") == today


def mark_done(col: str):
    st = load_state()
    st[f"matrix_{col}_last_date"] = beijing_now().strftime("%Y-%m-%d")
    save_state(st)


# ---------------------------------------------------------------- 启动对账

def reconcile_today_posts() -> dict:
    """拉今日已发微博, 返回 {col: True}(按话题标签匹配栏目)
    state 丢失(环境重启)场景下防止重复发帖。"""
    found = {}
    try:
        sys.path.insert(0, BASE)
        from matrix_common import load_config
        from weibo_client import WeiboClient
        cfg = load_config()
        client = WeiboClient(cfg["weibo_cookie"])
        uid = client.uid
        import urllib.request
        req = urllib.request.Request(
            f"https://weibo.com/ajax/statuses/mymblog?uid={uid}&page=1&feature=0",
            headers={"Cookie": cfg["weibo_cookie"],
                     "User-Agent": "Mozilla/5.0", "Referer": "https://weibo.com/"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        today = beijing_now().strftime("%Y-%m-%d")
        today_posts = []            # [(created_dt, text)] 今日全部帖
        for post in (d.get("data", {}).get("list") or []):
            ca = post.get("created_at", "")
            # weibo 返回 "Wed Oct 22 08:33:35 +0800 2026" 字符串(部分场景为秒级数字)
            try:
                if isinstance(ca, (int, float)):
                    created = datetime.datetime.fromtimestamp(ca, BJT)
                else:
                    created = datetime.datetime.strptime(
                        str(ca), "%a %b %d %H:%M:%S %z %Y")
                if created.strftime("%Y-%m-%d") != today:
                    continue
            except (ValueError, TypeError):
                continue
            text = post.get("text_raw", "") or post.get("text", "")
            today_posts.append((created, text))
            for col, conf in COLUMNS.items():
                if conf["tag"] in text:
                    found[col] = True
        # 时间窗兜底(2026-10-30 实测: 文案不带话题标签时 tag 匹配全失败,
        # 回滚清 state 后 catch-up 重发当日已发档 morning×3/yiyan×2):
        # 档期 ±90 分钟内有任意帖 → 视为该栏目已发(宁可少发不重发)
        for col, conf in COLUMNS.items():
            if found.get(col):
                continue
            hh, mm = conf["slot"]
            w0 = beijing_now().replace(
                hour=hh, minute=mm, second=0, microsecond=0)
            lo, hi = w0 - datetime.timedelta(minutes=90), \
                w0 + datetime.timedelta(minutes=90)
            if any(lo <= t <= hi for t, _ in today_posts):
                found[col] = True
    except Exception as e:
        log(f"   [warn] 对账失败(退回state判断): {e}")
    return found


def catch_up(now_bjt=None):
    """启动补发: 已过档期且state无记录 → 对账后补发"""
    now = now_bjt or beijing_now()
    posted = reconcile_today_posts()
    for col in active_columns():
        if column_done(col, now) or col in posted:
            if col in posted and not column_done(col, now):
                mark_done(col)
                log(f"[{col}] 对账发现今日已发, 补写标记")
            continue
        hh, mm = COLUMNS[col]["slot"]
        slot_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now >= slot_dt:
            log(f"[{col}] 档期({hh:02d}:{mm:02d})已过且未发, 补发")
            run_column(col)


# ---------------------------------------------------------------- 执行

def run_column(col: str) -> bool:
    script = COLUMNS[col]["script"]
    log(f"[{col}] 开始执行 {script}")
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(BASE, script)],
            capture_output=True, text=True, timeout=1800, cwd=BASE)
        ok = r.returncode == 0
        tail = (r.stdout or "").strip().split("\n")[-3:]
        log(f"[{col}] {'✅ 完成' if ok else '❌ 失败'} (rc={r.returncode}) | "
            + " / ".join(tail)[:400])
        if r.returncode != 0:
            log(f"[{col}] stderr: {(r.stderr or '')[-600:]}")
        return ok
    except subprocess.TimeoutExpired:
        log(f"[{col}] ❌ 超时(30分钟)")
        return False
    except Exception:
        log(f"[{col}] ❌ 异常: {traceback.format_exc()[-400:]}")
        return False


def main():
    cols = active_columns()
    log(f"调度器启动(矩阵版): 档期 {cols}, 北京时间 {beijing_now():%Y-%m-%d %H:%M}")
    print(f"[scheduler] 启动, 档期 {cols}")
    catch_up()
    fails = {c: 0 for c in cols}
    next_retry = {c: 0 for c in cols}          # epoch秒, 失败后最早重试时间

    while True:
        now = beijing_now()
        for c in cols:
            if column_done(c, now):
                continue
            if time.time() < next_retry[c]:
                continue
            hh, mm = COLUMNS[c]["slot"]
            if now < now.replace(hour=hh, minute=mm, second=0, microsecond=0):
                continue
            if run_column(c):
                mark_done(c)
                fails[c] = 0
            else:
                fails[c] += 1
                if fails[c] >= MAX_RETRY:
                    log(f"[{c}] 连续失败 {fails[c]} 次, 今日放弃")
                    mark_done(c)
                    fails[c] = 0
                else:
                    next_retry[c] = time.time() + RETRY_INTERVAL
                    log(f"[{c}] 第 {fails[c]} 次失败, "
                        f"{RETRY_INTERVAL // 60} 分钟后重试")
        time.sleep(60)


if __name__ == "__main__":
    main()

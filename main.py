# -*- coding: utf-8 -*-
"""微博 AI 资讯自动运营 · 统一入口

两个系列(均为每日更新):
  agi  AGI 日报     腾讯研究院 AI 速递(微信合集页实时源)  08:30 北京时间
  ai   AI 情报站    aihot.news 24h 精选资讯                12:00 北京时间

用法:
  python main.py status              # 查看 cookie 登录态 + 防重状态
  python main.py agi  --dry-run      # AGI 日报干跑(只构造不发布)
  python main.py agi                 # AGI 日报正式发布
  python main.py ai   --dry-run      # AI 情报站干跑
  python main.py ai                  # AI 情报站正式发布
  python main.py scheduler           # 启动常驻调度器
"""
import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")


def read_json(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def cmd_status():
    from weibo_client import WeiboClient
    cfg = read_json(CONFIG_PATH)
    state = read_json(STATE_PATH)
    print("=" * 50)
    print("微博 AI 资讯运营 · 状态")
    print("=" * 50)
    if not cfg.get("weibo_cookie"):
        print("❌ config.json 缺 weibo_cookie")
        return 1
    try:
        client = WeiboClient(cfg["weibo_cookie"])
        me = client.whoami()
        print(f"✅ 登录正常: {me['nick']} (uid={me['uid']})")
    except Exception as e:
        print(f"❌ 登录异常: {e}")
        return 1
    print(f"AGI 日报: 上期已发 {state.get('weibo_agi_last_issue', '无')}"
          f" | 今日运行: {state.get('weibo_agi_run_date', '无')}")
    print(f"AI 情报站: 上次已发 {state.get('weibo_ai_last_date', '无')}")
    wp = cfg.get("weibo_post", {})
    print(f"调度档期: agi={'on' if wp.get('agi_enabled', True) else 'off'} "
          f"ai={'on' if wp.get('ai_enabled', True) else 'off'}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("status", help="登录态与防重状态")
    p_agi = sub.add_parser("agi", help="AGI 日报(立即执行一次)")
    p_ai = sub.add_parser("ai", help="AI 情报站(立即执行一次)")
    for p in (p_agi, p_ai):
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--force", action="store_true")
        p.add_argument("--no-image", action="store_true")
    sub.add_parser("scheduler", help="启动常驻调度器")

    args = ap.parse_args()
    if args.cmd == "status":
        sys.exit(cmd_status())
    elif args.cmd == "agi":
        import agi_daily
        sys.exit(0 if agi_daily.run(args.dry_run, args.force,
                                    args.no_image) or True else 1)
    elif args.cmd == "ai":
        import ai_news
        sys.exit(0 if ai_news.run(args.dry_run, args.force,
                                  args.no_image) or True else 1)
    elif args.cmd == "scheduler":
        import scheduler
        scheduler.main()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()

#!/bin/bash
# 微博调度器 watchdog: 进程死了 5 秒内自动拉起
cd "$(dirname "$0")"
while true; do
  if ! pgrep -f "weibo-agi-poster/scheduler.py" > /dev/null; then
    nohup python3 /home/z/my-project/weibo-agi-poster/scheduler.py >> /home/z/my-project/weibo-agi-poster/scheduler.log 2>&1 &
    echo "[watchdog] $(date '+%F %T') 拉起 scheduler (PID $!)" >> /home/z/my-project/weibo-agi-poster/scheduler.log
  fi
  sleep 5
done

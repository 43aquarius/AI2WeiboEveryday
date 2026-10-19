#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""守护进程启动器(双 fork 脱离会话, 沙箱环境实测可常驻)

用法: python3 run_daemon.py
原理: 双 fork + setsid 脱离控制终端与进程组, 规避会话级进程回收;
      守护循环内 watchdog 拉起 scheduler.py, 意外退出 10 秒后自动重启。
"""
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "scheduler.log")


def daemonize() -> bool:
    """成功成为守护进程返回 True(子进程侧), 父进程侧返回 False"""
    pid = os.fork()
    if pid > 0:
        return False                    # 原进程: 退出返回
    os.setsid()                         # 新会话(脱离终端/进程组)
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)                     # 中间进程退出, 守护进程不再组长
    sys.stdout.flush()
    sys.stderr.flush()
    log = open(LOG, "a")
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)
    os.chdir(BASE)
    return True


def main():
    if not daemonize():
        print("daemon 已 fork 到后台(双 fork 脱离会话)")
        return
    while True:
        try:
            r = subprocess.run([sys.executable,
                                os.path.join(BASE, "scheduler.py")])
            print(f"[daemon] scheduler 退出 rc={r.returncode}, "
                  f"10秒后重启", flush=True)
        except Exception as e:
            print(f"[daemon] 异常: {e}", flush=True)
        time.sleep(10)


if __name__ == "__main__":
    main()

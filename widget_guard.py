# -*- coding: utf-8 -*-
"""Magpie 额度浮窗的守护进程（常驻，开机自启时由启动项拉起）。

- 每 10 秒探一次浮窗的单实例端口（默认 5599），不通就重新拉起
- 用户主动点 × 关闭会写 widget_off.flag，守护看到就不再拉起
- 想恢复：双击 install.ps1 装出来的桌面快捷方式，它会删掉 flag

环境变量：
  MAGPIE_BASE          网关地址，默认 http://127.0.0.1:3425
  QUOTA_WIDGET_PORT    单实例锁端口，默认 5599
  PYTHONW              指定 pythonw.exe 路径，默认自动找
"""
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "quota_widget.py")
FLAG = os.path.join(HERE, "widget_off.flag")
PORT = int(os.environ.get("QUOTA_WIDGET_PORT", "5599"))


def find_pythonw():
    """优先用环境变量，其次用当前解释器的 pythonw，再退回 PATH。"""
    forced = os.environ.get("PYTHONW")
    if forced and os.path.exists(forced):
        return forced
    exe = sys.executable or ""
    if exe.lower().endswith("python.exe"):
        cand = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(cand):
            return cand
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(cand):
        return cand
    return "pythonw"


PYW = find_pythonw()


def widget_alive():
    s = socket.socket()
    s.settimeout(0.6)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        s.close()


def launch():
    try:
        return subprocess.Popen(
            [PYW, SCRIPT],
            cwd=HERE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
    except Exception:
        return None


def main():
    child = None
    last_launch = 0.0
    while True:
        try:
            alive = widget_alive()
            # 刚拉起、还在启动的进程也算活着，避免重复拉
            if not alive and child is not None and child.poll() is None:
                alive = True
            if not alive and not os.path.exists(FLAG):
                if time.time() - last_launch > 20:
                    child = launch()
                    last_launch = time.time()
        except Exception:
            pass
        time.sleep(10)


if __name__ == "__main__":
    if sys.stdout is None:  # pythonw 下 stdout 是 None
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    main()

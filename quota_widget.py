# -*- coding: utf-8 -*-
"""Magpie Quota Widget —— Magpie 网关额度浮窗。

一块常驻桌面(右下角)的深色小面板，直接读 Magpie 网关的
/v1/magpie/quotas、/v1/magpie/route，实时告诉你：

  · 当前这次调用落在哪个 routing group 上、用的是哪个模型
  · 这个组的模型在强弱榜上的名次
  · 各平台额度还剩多少百分比、还有多久重置

设计要点：
  1. 所有坐标用"逻辑像素"设计，显示时乘 DPI 比例 → 150% 缩放不会挤压
  2. 右键菜单：大小 / 透明度 / 置顶 / 跟随 Magpie / 隐藏付费额度 / 开机自启
  3. 单实例（端口锁），守护进程 widget_guard.py 负责挂了自动拉起
  4. 只读 HTTP，不写入网关，不动账号，token 一律不落盘

环境变量：
  MAGPIE_BASE        网关地址，默认 http://127.0.0.1:3425
  QUOTA_WIDGET_PORT  单实例锁端口，默认 5599

纯标准库（tkinter + urllib），不需要 pip install 任何东西。
"""
import ctypes
import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import tkinter as tk
import tkinter.font as tkfont

# Magpie 网关地址：默认本机 3425，可用环境变量改（远程/容器都能用）
GATEWAY = os.environ.get("MAGPIE_BASE", "http://127.0.0.1:3425").rstrip("/")
# 单实例锁端口：同一台机器要开多个浮窗（看不同网关）时改成别的
WIDGET_PORT = int(os.environ.get("QUOTA_WIDGET_PORT", "5599"))
REQ_LIMIT = 60
ACTIVE_MIN = 8
QUOTA_HOURS = 36
POLL_REQ = 8
POLL_QUOTA = 20
POLL_MODELS = 300

# 逻辑尺寸（设计稿），实际像素 = 逻辑 * DPI 比例
W, H = 356, 252
HEAD_H = 42
RADIUS = 16

C_BG     = "#14161c"
C_BG2    = "#1a1f29"
C_BORDER = "#272d3b"
C_TEXT   = "#f3f5f9"
C_TEXT2  = "#a8b0c0"
C_DIM    = "#7b8394"
C_DIM2   = "#5a6272"
C_OK     = "#4ade80"
C_WARN   = "#fbbf24"
C_ORANGE = "#fb923c"
C_BAD    = "#f87171"
C_ACCENT = "#8b9dff"
C_TICK   = "#8fb6ff"
KEY      = "#0a0b0e"

HERE = os.path.dirname(os.path.abspath(__file__))
POS_FILE = os.path.join(HERE, "widget_pos.json")

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TZ8 = timezone(timedelta(hours=8))


def http_json(path):
    with _opener.open(GATEWAY + path, timeout=6) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_time(s):
    if not s:
        return None
    s = str(s).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if "." in s and "+" in s:
            head, tz = s.split("+", 1)
            h, _, frac = head.partition(".")
            if frac:
                head = h + "." + frac[:6]
            s = head + "+" + tz
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ8)
        return dt.astimezone(TZ8)
    except ValueError:
        return None


def ago_text(dt):
    sec = max(0, (datetime.now(TZ8) - dt).total_seconds())
    if sec < 60:
        return "%d秒前" % sec
    if sec < 3600:
        return "%d分前" % (sec // 60)
    return "%.1f时前" % (sec / 3600)


def countdown_text(dt):
    sec = (dt - datetime.now(TZ8)).total_seconds()
    if sec <= 0:
        return "到时"
    if sec < 3600:
        return "%d分" % (sec // 60)
    if sec < 86400:
        return "%.1f时" % (sec / 3600)
    return "%.0f天" % (sec / 86400)


def short_name(p):
    n = (p or "").strip()
    for a, b in (("msmoli", ""), ("magpie ", ""), ("Raccoon", "raccoon"),
                 ("AutoClaw 国内", "AC国内"), ("AutoClaw", "AC"),
                 ("WorkBuddy AI", "WB AI")):
        n = n.replace(a, b)
    return n.strip() or "?"


PROV_SHORT = {"workbuddy": "WB", "workbuddy-ai": "WB-AI", "loomy": "讯飞",
              "raccoon": "小浣熊", "modelscope": "魔搭", "qoder": "Qoder",
              "qoder-cn": "Qoder", "autoclaw": "AC", "autoclaw-cn": "AC",
              "minimax-code": "MM", "minimax-code-global": "MM", "trae-cn": "Trae",
              "trae-global": "Trae", "openrouter": "OR", "qwenwork": "Qwen"}


def prov_short(pid):
    pid = (pid or "").lower()
    if pid in PROV_SHORT:
        return PROV_SHORT[pid]
    for k, v in PROV_SHORT.items():
        if pid.startswith(k):
            return v
    return (pid or "?")[:4]


def pct_color(pct):
    if pct <= 0.001:
        return C_BAD
    if pct < 20:
        return C_ORANGE
    if pct < 50:
        return C_WARN
    return C_OK


class Data:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = []
        self.quotas = []
        self.providers = []
        self.groups = {}
        self.names = {}
        self.rank = []
        self.routes = []
        self.online = False
        self.updated = ""
        self.hidden = set()      # 不显示在额度列表里的 provider id 前缀

    def refresh_models(self):
        try:
            d = http_json("/v1/models")
            g, names = {}, {}
            for m in d.get("data", []):
                mid = m.get("id", "")
                dn = m.get("display_name") or ""
                if mid.startswith("group/"):
                    g[mid.split("/", 1)[1]] = dn or mid
                if dn:
                    names[mid] = dn
            with self.lock:
                self.groups = g
                self.names = names
        except Exception:
            pass

    def refresh_rank(self):
        """可选：读同目录（或上一级）的 model_rank.json，给模型加个强弱名次。
        没有这个文件也能跑，只是不显示 #名次。"""
        import re as _re
        table = []
        for path in (os.path.join(HERE, "model_rank.json"),
                     os.path.join(os.path.dirname(HERE), "model_rank.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    table = json.load(f).get("table", [])
                break
            except Exception:
                continue
        if not table:
            return

        def norm(x):
            x = (x or "").lower()
            x = _re.sub(r"\((max|high|xhigh|medium|low|preview)\)", " ", x)
            x = _re.sub(r"[-_ ]?\d{6,8}$", " ", x)
            return _re.sub(r"[^a-z0-9.]", "", x)

        rows = [(norm(r.get("model")), int(r.get("rank", 0))) for r in table]
        rows = [r for r in rows if r[0] and r[1]]
        with self.lock:
            self.rank = rows

    ALIAS = {"星火": "Spark-X2.6", "混元": "Hy4"}

    def rank_of(self, label):
        import difflib
        label = label or ""
        for cn, en in self.ALIAS.items():
            if cn in label:
                label = en
                break
        key = "".join(ch for ch in label.lower() if ch.isalnum() or ch == ".")
        if not key:
            return None
        with self.lock:
            rows = list(self.rank)
        best, best_r = None, 0.0
        for cand, rk in rows:
            if cand == key:
                return rk
            if cand.startswith(key) or key.startswith(cand) or key in cand:
                ratio = 0.9
            else:
                ratio = difflib.SequenceMatcher(None, key, cand).ratio()
            if ratio > best_r:
                best, best_r = rk, ratio
        return best if best_r >= 0.75 else None

    def refresh_requests(self):
        try:
            d = http_json("/v1/magpie/usage/requests?limit=%d" % REQ_LIMIT)
            with self.lock:
                self.rows = d.get("rows", [])
                self.online = True
                self.updated = datetime.now(TZ8).strftime("%H:%M")
        except Exception:
            with self.lock:
                self.online = False

    def refresh_quotas(self):
        try:
            d = http_json("/v1/magpie/quotas")
            now = datetime.now(TZ8)
            near, allp = [], []
            for p in d.get("data", []):
                pid = (p.get("provider") or "").lower()
                name_low = (p.get("name") or "").lower()
                if any(pid.startswith(h) or name_low.startswith(h) for h in self.hidden):
                    continue
                wins = []
                for w in p.get("windows", []):
                    if w.get("remaining") is None:
                        continue
                    wins.append({"name": w.get("name", ""), "display": w.get("display", ""),
                                 "pct": float(w["remaining"])})
                    rst = parse_time(w.get("resetsAt"))
                    if rst is not None and not (timedelta(0) < rst - now < timedelta(hours=QUOTA_HOURS)):
                        continue
                    if float(w["remaining"]) <= 0.001 and rst is None:
                        continue
                    near.append({"provider": p.get("name") or p.get("provider", "?"),
                                 "display": w.get("display", ""),
                                 "pct": float(w["remaining"]), "reset": rst})
                allp.append({"id": p.get("provider", ""), "name": p.get("name", ""),
                             "user": str(p.get("user") or ""), "windows": wins})
            near.sort(key=lambda x: (x["reset"] is None, x["reset"] or now))
            merged = {}
            for ln in near:
                key = short_name(ln["provider"])
                m = merged.get(key)
                if m is None:
                    merged[key] = dict(ln, n=1, name=key)
                else:
                    m["n"] += 1
                    if ln["pct"] < m["pct"]:
                        m["pct"] = ln["pct"]
                    if ln["reset"] and (m["reset"] is None or ln["reset"] < m["reset"]):
                        m["reset"] = ln["reset"]
            out = sorted(merged.values(),
                         key=lambda x: (0 if x["pct"] < 50 or x["reset"] and
                                        (x["reset"] - now).total_seconds() < 3600 else 1,
                                        x["reset"] is None, x["reset"] or now))
            with self.lock:
                self.quotas = out
                self.providers = allp
                self.online = True
        except Exception:
            with self.lock:
                self.online = False

    @staticmethod
    def pick_window(wins, model):
        if not wins:
            return None
        low = (model or "").lower()
        for w in wins:
            nm = w["name"].lower()
            if low and low in nm and "token" in nm:
                return w
        for w in wins:
            if "total" in w["name"].lower():
                return w
        return wins[0]

    def quota_for(self, provider_id, model):
        with self.lock:
            provs = list(self.providers)
        cands = [p for p in provs if p["id"] == provider_id]
        if not cands:
            cands = [p for p in provs if provider_id and provider_id in (p["id"] or "")]
        best = None
        for p in cands:
            w = self.pick_window(p["windows"], model)
            if not w:
                continue
            e = {"pct": w["pct"], "display": w["display"], "account": p["user"]}
            if best is None or w["pct"] < best["pct"]:
                best = e
        return best

    def refresh_routes(self):
        with self.lock:
            rows = list(self.rows)
            groups = dict(self.groups)
        now = datetime.now(TZ8)
        seen = []
        for r in rows:
            sid = r.get("session")
            t = parse_time(r.get("t"))
            if not sid or not t or not r.get("model"):
                continue
            if (now - t).total_seconds() > ACTIVE_MIN * 60:
                continue
            if sid not in seen:
                seen.append(sid)
            if len(seen) >= 4:
                break
        routes = []
        for sid in seen:
            try:
                d = http_json("/v1/magpie/route?session=%s" % sid)
            except Exception:
                continue
            rt = d.get("route") or {}
            asked = rt.get("asked") or ""
            served = rt.get("served") or ""
            raw = rt.get("model") or ""
            provider = raw.split("/", 1)[0] if "/" in raw else ""
            disp = (served or raw).split("/", 1)[-1] if (served or raw) else ""
            gid = asked.split("/", 1)[1] if asked.startswith("group/") else ""
            gname = groups.get(gid) or (gid or disp or "直连")
            q = self.quota_for(provider, disp)
            with self.lock:
                label = self.names.get(raw) or self.names.get(disp) or ""
            shown = label or disp or raw
            if not shown:
                continue
            routes.append({
                "group": gname,
                "rank": self.rank_of(shown),
                "model": shown,
                "provider": provider,
                "account": (q or {}).get("account", ""),
                "pct": (q or {}).get("pct"),
                "ago": ago_text(parse_time(rt.get("time")) or now),
                "ts": parse_time(rt.get("time")) or now,
                "n": self.tokens_for(disp),
            })
        uniq, keys = [], set()
        for r in sorted(routes, key=lambda x: (x["n"], x["ts"]), reverse=True):
            k = (r["group"], r["model"])
            if k in keys:
                continue
            keys.add(k)
            uniq.append(r)
        with self.lock:
            self.routes = uniq

    def tokens_for(self, model):
        now = datetime.now(TZ8)
        total = 0
        with self.lock:
            rows = list(self.rows)
        for r in rows:
            t = parse_time(r.get("t"))
            if t and (now - t).total_seconds() < 600 and r.get("model") == model:
                total += int(r.get("in", 0) or 0) + int(r.get("out", 0) or 0)
        return total


CFG_FILE = os.path.join(HERE, "widget_config.json")
DEFAULTS = {"scale": 1.0, "alpha": 1.0, "topmost": True, "follow": True,
            "x": None, "y": None, "folded": False,
            "hide_paid": True}
BASE_FONTS = {"title": 11, "group": 10, "pct": 10, "model": 8,
              "label": 7, "quota": 8, "tiny": 7}


def load_cfg():
    cfg = dict(DEFAULTS)
    try:
        with open(CFG_FILE, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_cfg(cfg):
    try:
        with open(CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def magpie_running():
    """有没有 magpie.exe 在跑（toolhelp 枚举，不启动子进程）"""
    import ctypes
    import ctypes.wintypes as wt

    class PE32(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                    ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]

    k = ctypes.windll.kernel32
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    if snap == -1:
        return True
    try:
        e = PE32()
        e.dwSize = ctypes.sizeof(PE32)
        ok = k.Process32First(snap, ctypes.byref(e))
        while ok:
            if b"magpie" in e.szExeFile.lower():
                return True
            ok = k.Process32Next(snap, ctypes.byref(e))
        return False
    finally:
        k.CloseHandle(snap)


class Float:
    def __init__(self, root):
        self.root = root
        self.cfg = load_cfg()
        root.overrideredirect(True)
        root.configure(bg=KEY)
        try:
            root.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass

        try:
            self.dpi = max(1.0, round(root.winfo_fpixels("1i") / 96.0, 2))
        except Exception:
            self.dpi = 1.0
        self.user_scale = float(self.cfg.get("scale") or 1.0)
        self.S = self.dpi * self.user_scale

        self.fam = self.pick_font()
        self.build_fonts()

        self.c = tk.Canvas(root, width=self.px(W), height=self.px(H),
                           bg=KEY, highlightthickness=0, bd=0)
        self.c.pack()

        self.data = Data()
        self.apply_hidden()
        self.folded = bool(self.cfg.get("folded"))
        self.hidden = False
        self.win = None
        self._drag = None
        self._pos_saved = None

        self.apply_topmost(bool(self.cfg.get("topmost", True)))
        self.apply_alpha(float(self.cfg.get("alpha") or 1.0))
        self.load_pos()
        self.bind()
        self.threads()
        self.render_loop()
        threading.Thread(target=self.follow_loop, daemon=True).start()

    # ---------- 缩放与字体 ----------
    def px(self, v):
        return int(round(v * self.S))

    def build_fonts(self):
        def f(key, weight="normal"):
            return tkfont.Font(family=self.fam,
                               size=max(6, int(round(BASE_FONTS[key] * self.user_scale))),
                               weight=weight)

        self.f_title = f("title", "bold")
        self.f_group = f("group", "bold")
        self.f_pct = f("pct", "bold")
        self.f_model = f("model")
        self.f_label = f("label")
        self.f_quota = f("quota")
        self.f_tiny = f("tiny")

    def pick_font(self):
        for fam in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"):
            try:
                if tkfont.Font(family=fam, size=9).actual("family") == fam:
                    return fam
            except tk.TclError:
                continue
        return "TkDefaultFont"

    def zoom(self, direction):
        step = 0.05 if direction > 0 else -0.05
        self.set_scale(round(self.user_scale + step, 2))

    def set_scale(self, s):
        s = max(0.7, min(1.6, float(s)))
        if abs(s - self.user_scale) < 0.001:
            return
        # 以右下角为锚点缩放，位置不会跑
        x, y = self.root.winfo_x(), self.root.winfo_y()
        ow, oh = self.px(W), self.px(HEAD_H if self.folded else H)
        rx, by = x + ow, y + oh
        self.user_scale = s
        self.S = self.dpi * s
        self.build_fonts()
        nw, nh = self.px(W), self.px(HEAD_H if self.folded else H)
        self.root.geometry("%dx%d+%d+%d" % (nw, nh, max(0, rx - nw), max(0, by - nh)))
        self.c.config(width=nw, height=nh)
        self.cfg["scale"] = s
        self.save_cfg()
        self.draw()

    def apply_alpha(self, a):
        a = max(0.4, min(1.0, float(a)))
        try:
            if a >= 0.999:
                self.root.attributes("-alpha", 1.0)
            else:
                self.root.attributes("-alpha", a)
        except tk.TclError:
            pass
        self.cfg["alpha"] = a

    def set_alpha(self, a):
        self.apply_alpha(a)
        self.save_cfg()

    def apply_topmost(self, on):
        self.topmost = bool(on)
        try:
            self.root.attributes("-topmost", self.topmost)
        except tk.TclError:
            pass
        self.cfg["topmost"] = self.topmost

    def set_topmost(self, on):
        self.apply_topmost(on)
        self.save_cfg()

    def set_follow(self, on):
        self.cfg["follow"] = bool(on)
        self.save_cfg()

    def apply_hidden(self):
        """付费、自己在别处掌控的额度（WorkBuddy）不进"当天要用完"列表"""
        self.data.hidden = {"workbuddy"} if self.cfg.get("hide_paid", True) else set()
        self.data.refresh_quotas()

    def set_hide_paid(self, on):
        self.cfg["hide_paid"] = bool(on)
        self.apply_hidden()
        self.save_cfg()
        self.draw()

    # ---------- 开机自启（写启动文件夹，跟随登录） ----------
    def startup_path(self):
        base = os.path.join(os.environ.get("APPDATA", ""),
                            r"Microsoft\Windows\Start Menu\Programs\Startup")
        return os.path.join(base, "MagpieQuotaWidget.bat")

    def autostart_on(self):
        return os.path.exists(self.startup_path())

    def set_autostart(self, on):
        path = self.startup_path()
        try:
            if on:
                py = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                                  r"Programs\Python\Python313\pythonw.exe")
                if not os.path.exists(py):
                    py = "pythonw"
                body = ('@echo off\r\nchcp 65001 >nul\r\ncd /d "%s"\r\n'
                        'start "" "%s" "%s"\r\n' % (HERE, py, os.path.join(HERE, "quota_widget.py")))
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(body)
            elif os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        self.cfg["autostart"] = bool(on)
        self.save_cfg()

    # ---------- 位置 ----------
    def load_pos(self):
        x, y = self.cfg.get("x"), self.cfg.get("y")
        h = HEAD_H if self.folded else H
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # 历史上坐标会被 DPI 反复放大（每次 ×1.5），最后漂到屏幕外变成"浮标消失"。
        # 这里做一次哨兵：任何跑出可视区的坐标一律回到右下角，别再往外漂。
        off = (x is None or y is None
               or x < 0 or y < 0
               or x > sw - 60 or y > sh - 60)
        if off:
            x, y = sw - self.px(W) - 24, sh - self.px(h) - 90
        self.root.geometry("%dx%d+%d+%d" % (self.px(W), self.px(h), int(x), int(y)))

    def save_pos(self):
        try:
            self.cfg["x"] = self.root.winfo_x()
            self.cfg["y"] = self.root.winfo_y()
            self.cfg["folded"] = self.folded
            save_cfg(self.cfg)
        except Exception:
            pass

    def reset_pos(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        h = HEAD_H if self.folded else H
        self.root.geometry("+%d+%d" % (sw - self.px(W) - 24, sh - self.px(h) - 90))
        self.save_pos()

    def save_cfg(self):
        self.save_pos()

    # ---------- 显隐 ----------
    def hide_win(self):
        if not self.hidden:
            self.hidden = True
            self.root.withdraw()

    def show_win(self):
        if self.hidden:
            self.hidden = False
            self.root.deiconify()
            self.root.attributes("-topmost", self.topmost)

    def follow_loop(self):
        """Magpie 起来就出现，退出就收起"""
        last = None
        while True:
            try:
                on = magpie_running()
                if self.cfg.get("follow", True) and on != last:
                    last = on
                    if on:
                        self.root.after(0, self.show_win)
                    else:
                        self.root.after(0, self.hide_win)
            except Exception:
                pass
            time.sleep(5)

    # ---------- 右键菜单 ----------
    def build_menu(self):
        kw = dict(tearoff=0, bg=C_BG2, fg=C_TEXT, activebackground=C_BORDER,
                  activeforeground=C_TEXT, bd=0, font=self.f_model)
        m = tk.Menu(self.root, **kw)

        size = tk.Menu(m, **kw)
        for label, val in (("小  85%", 0.85), ("标准 100%", 1.0),
                           ("大  115%", 1.15), ("特大 130%", 1.3)):
            size.add_command(label=label, command=lambda v=val: self.set_scale(v))
        m.add_cascade(label="大小", menu=size)

        alpha = tk.Menu(m, **kw)
        for label, val in (("不透明 100%", 1.0), ("95%", 0.95), ("90%", 0.9),
                           ("80%", 0.8), ("70%", 0.7), ("半透明 55%", 0.55)):
            alpha.add_command(label=label, command=lambda v=val: self.set_alpha(v))
        m.add_cascade(label="透明度", menu=alpha)

        m.add_separator()
        m.add_checkbutton(label="窗口置顶", onvalue=True, offvalue=False,
                          variable=self.var_top, command=lambda: self.set_topmost(self.var_top.get()))
        m.add_checkbutton(label="跟随 Magpie 自动显示", onvalue=True, offvalue=False,
                          variable=self.var_follow, command=lambda: self.set_follow(self.var_follow.get()))
        m.add_checkbutton(label="隐藏 WorkBuddy 付费额度", onvalue=True, offvalue=False,
                          variable=self.var_paid, command=lambda: self.set_hide_paid(self.var_paid.get()))
        m.add_checkbutton(label="开机自动启动", onvalue=True, offvalue=False,
                          variable=self.var_auto, command=lambda: self.set_autostart(self.var_auto.get()))
        m.add_separator()
        m.add_command(label="折叠 / 展开", command=self.toggle_fold)
        m.add_command(label="复位到右下角", command=self.reset_pos)
        m.add_command(label="设置…", command=self.open_settings)
        m.add_separator()
        m.add_command(label="关闭浮窗", command=self.quit)
        return m

    def on_right(self, e):
        self.var_top.set(self.topmost)
        self.var_follow.set(bool(self.cfg.get("follow", True)))
        self.var_auto.set(self.autostart_on())
        self.var_paid.set(bool(self.cfg.get("hide_paid", True)))
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def open_settings(self):
        if self.win and self.win.winfo_exists():
            self.win.lift()
            return
        w = tk.Toplevel(self.root)
        self.win = w
        w.title("浮窗设置")
        w.configure(bg=C_BG)
        w.geometry("320x330+%d+%d" % (self.root.winfo_x() - 330, self.root.winfo_y()))
        w.attributes("-topmost", True)

        def lab(txt, y):
            tk.Label(w, text=txt, bg=C_BG, fg=C_TEXT2, font=self.f_model).place(x=18, y=y)

        lab("大小", 14)
        s1 = tk.Scale(w, from_=70, to=160, orient="horizontal", length=200,
                      bg=C_BG, fg=C_TEXT, highlightthickness=0, troughcolor=C_BG2, bd=0)
        s1.set(int(self.user_scale * 100))
        s1.configure(command=lambda v: self.set_scale(float(v) / 100.0))
        s1.place(x=100, y=8)

        lab("透明度", 54)
        s2 = tk.Scale(w, from_=40, to=100, orient="horizontal", length=200,
                      bg=C_BG, fg=C_TEXT, highlightthickness=0, troughcolor=C_BG2, bd=0)
        s2.set(int(float(self.cfg.get("alpha", 1.0)) * 100))
        s2.configure(command=lambda v: self.set_alpha(float(v) / 100.0))
        s2.place(x=100, y=48)

        v1 = tk.BooleanVar(value=self.topmost)
        v2 = tk.BooleanVar(value=bool(self.cfg.get("follow", True)))
        v3 = tk.BooleanVar(value=self.autostart_on())
        for i, (txt, var, cmd) in enumerate((
                ("窗口置顶", v1, lambda: self.set_topmost(v1.get())),
                ("跟随 Magpie 自动显示", v2, lambda: self.set_follow(v2.get())),
                ("开机自动启动", v3, lambda: self.set_autostart(v3.get())))):
            cb = tk.Checkbutton(w, text=txt, variable=var, bg=C_BG, fg=C_TEXT,
                                selectcolor=C_BG2, activebackground=C_BG,
                                activeforeground=C_TEXT, bd=0, highlightthickness=0,
                                font=self.f_model, command=cmd)
            cb.place(x=16, y=100 + i * 30)

        tk.Label(w, text="右键浮窗可随时改大小 / 透明度 / 关闭",
                 bg=C_BG, fg=C_DIM2, font=self.f_tiny).place(x=16, y=196)

        tk.Button(w, text="复位到右下角", bg=C_BG2, fg=C_TEXT, bd=0, font=self.f_model,
                  activebackground=C_BORDER, command=self.reset_pos).place(x=16, y=226, width=130, height=30)
        tk.Button(w, text="关闭", bg=C_BG2, fg=C_TEXT, bd=0, font=self.f_model,
                  activebackground=C_BORDER, command=w.destroy).place(x=164, y=226, width=130, height=30)

        def on_close():
            w.destroy()
            self.win = None
        w.protocol("WM_DELETE_WINDOW", on_close)

    # ---------- 基础 ----------
    def bind(self):
        self.c.bind("<ButtonPress-1>", self.on_press)
        self.c.bind("<B1-Motion>", self.on_drag)
        self.c.bind("<ButtonRelease-1>", self.on_release)
        self.c.bind("<Button-3>", self.on_right)
        self.var_top = tk.BooleanVar(value=self.topmost)
        self.var_follow = tk.BooleanVar(value=bool(self.cfg.get("follow", True)))
        self.var_auto = tk.BooleanVar(value=self.autostart_on())
        self.var_paid = tk.BooleanVar(value=bool(self.cfg.get("hide_paid", True)))
        self.menu = self.build_menu()
        for tag, cb in (("btn_fold", lambda e: self.toggle_fold()),
                        ("btn_close", lambda e: self.quit()),
                        ("zoom_minus", lambda e: self.zoom(-1)),
                        ("zoom_plus", lambda e: self.zoom(1)),
                        ("zoom_val", lambda e: self.set_scale(1.0))):
            self.c.tag_bind(tag, "<Button-1>", cb)
        self.c.tag_bind("btn_fold", "<Enter>", lambda e: self.c.itemconfig("btn_fold", fill=C_TEXT))
        self.c.tag_bind("btn_fold", "<Leave>", lambda e: self.c.itemconfig("btn_fold", fill=C_DIM2))
        self.c.tag_bind("btn_close", "<Enter>", lambda e: self.c.itemconfig("btn_close", fill=C_BAD))
        self.c.tag_bind("btn_close", "<Leave>", lambda e: self.c.itemconfig("btn_close", fill=C_DIM2))
        for tag in ("zoom_minus", "zoom_plus", "zoom_val"):
            self.c.tag_bind(tag, "<Enter>", lambda e, t=tag: self.c.itemconfig(t, fill=C_TEXT))
            self.c.tag_bind(tag, "<Leave>", lambda e, t=tag: self.c.itemconfig(t, fill=C_TEXT2))

    @staticmethod
    def _inside(x, y, bb, pad=4):
        return bb[0] - pad <= x <= bb[2] + pad and bb[1] - pad <= y <= bb[3] + pad

    def on_press(self, e):
        for tag in ("btn_fold", "btn_close", "zoom_minus", "zoom_plus", "zoom_val"):
            for it in self.c.find_withtag(tag):
                bb = self.c.bbox(it)
                if bb and self._inside(e.x, e.y, bb):
                    return
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def on_drag(self, e):
        if not self._drag:
            return
        self.root.geometry("+%d+%d" % (e.x_root - self._drag[0], e.y_root - self._drag[1]))

    def on_release(self, e):
        if self._drag:
            self._drag = None
            self.save_pos()

    def quit(self):
        self.save_pos()
        # 主动关闭：写标记，守护进程看到就不再自动拉起
        try:
            with open(os.path.join(HERE, "widget_off.flag"), "w", encoding="utf-8") as f:
                f.write("closed by user\n")
        except Exception:
            pass
        self.root.destroy()

    def toggle_fold(self):
        self.folded = not self.folded
        h = HEAD_H if self.folded else H
        self.root.geometry("%dx%d" % (self.px(W), self.px(h)))
        self.c.config(height=self.px(h))
        self.save_pos()
        self.draw()

    def threads(self):
        def loop(fn, gap):
            while True:
                fn()
                time.sleep(gap)

        def models_job():
            self.data.refresh_models()
            self.data.refresh_rank()

        threading.Thread(target=loop, args=(models_job, POLL_MODELS), daemon=True).start()
        threading.Thread(target=loop, args=(self.data.refresh_quotas, POLL_QUOTA), daemon=True).start()

        def req():
            while True:
                self.data.refresh_requests()
                self.data.refresh_routes()
                time.sleep(POLL_REQ)

        threading.Thread(target=req, daemon=True).start()

    # ---------- 绘制 ----------
    def rrect(self, x1, y1, x2, y2, r, fill, outline=None, width=1):
        import math
        s = self.S
        pts = []
        for cx, cy, a0 in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0),
                           (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
            for i in range(6):
                a = math.radians(a0 + i * 90 / 5.0)
                pts += [(cx + r * math.cos(a)) * s, (cy + r * math.sin(a)) * s]
        return self.c.create_polygon(pts, fill=fill, outline=outline or fill,
                                     width=max(1, int(width * s)))

    def dot(self, x, y, r, fill):
        s = self.S
        return self.c.create_oval((x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s,
                                  fill=fill, outline="")

    def text(self, x, y, txt, font=None, fill=C_TEXT, anchor="w", tags=None):
        kw = dict(text=txt, fill=fill, font=font or self.f_model, anchor=anchor)
        if tags:
            kw["tags"] = tags
        return self.c.create_text(self.px(x), self.px(y), **kw)

    def fit(self, text, font, maxw):
        if font.measure(text) <= maxw * self.S:
            return text
        while text and font.measure(text + "…") > maxw * self.S:
            text = text[:-1]
        return (text + "…") if text else "…"

    def render_loop(self):
        try:
            self.draw()
        except Exception:
            pass
        self.root.after(1000, self.render_loop)

    def draw(self):
        c = self.c
        c.delete("all")
        h = HEAD_H if self.folded else H
        self.rrect(0.5, 0.5, W - 0.5, h - 0.5, RADIUS, C_BG, C_BORDER, 1)

        with self.data.lock:
            online = self.data.online
            routes = list(self.data.routes)
            quotas = list(self.data.quotas)
            updated = self.data.updated

        self.dot(18, 22, 3.5, C_OK if online else C_BAD)
        self.text(28, 22, "模型监控", self.f_title)
        self.text(94, 23, updated if online else "离线", self.f_tiny, C_DIM2)
        # 缩放控制条：− 100% +
        self.rrect(240, 12, 306, 32, 10, "#1c2230")
        self.text(248, 22, "−", self.f_quota, C_TEXT2, "w", tags="zoom_minus")
        self.text(273, 22, "%d%%" % round(self.user_scale * 100), self.f_tiny, C_TEXT2, "center",
                  tags="zoom_val")
        self.text(298, 22, "+", self.f_quota, C_TEXT2, "e", tags="zoom_plus")

        self.text(340, 21, "×", self.f_title, C_DIM2, "e", tags="btn_close")
        self.text(322, 21, "—", self.f_title, C_DIM2, "e", tags="btn_fold")

        if self.folded:
            if routes:
                r = routes[0]
                tail = "%s · %s" % (r["group"], r["model"])
                if r.get("rank"):
                    tail += " #%d" % r["rank"]
                self.text(332, 22, self.fit(tail, self.f_tiny, 190), self.f_tiny, C_ACCENT, "e")
            return

        c.create_line(self.px(17), self.px(42), self.px(339), self.px(42),
                      fill=C_BORDER, width=1)

        self.text(17, 58, "正在调用", self.f_label, C_DIM2)
        if routes:
            for i, r in enumerate(routes[:3]):
                ry = 78 + i * 26
                pct = r["pct"]
                color = pct_color(pct) if pct is not None else C_DIM2
                self.dot(20, ry, 2.5, color)
                self.text(28, ry, self.fit(r["group"], self.f_group, 74),
                          self.f_group, C_ACCENT if i == 0 else C_TEXT)
                self.text(106, ry, prov_short(r.get("provider")), self.f_label, C_DIM2)
                label = r["model"]
                if r.get("rank"):
                    label = "%s #%d" % (label, r["rank"])
                self.text(141, ry, self.fit(label, self.f_model, 136), self.f_model, C_TEXT2)
                if pct is not None:
                    self.text(339, ry, "剩 %d%%" % int(pct), self.f_pct, color, "e")
                else:
                    self.text(339, ry, "—", self.f_pct, C_DIM2, "e")
        else:
            self.text(17, 80, "暂无活跃调用", self.f_model, C_DIM)
            self.text(17, 102, "有调用时这里显示 组 · 模型 · 剩余额度", self.f_tiny, C_DIM2)

        c.create_line(self.px(17), self.px(152), self.px(339), self.px(152),
                      fill="#20252f", width=1)

        self.text(17, 166, "当天要用完", self.f_label, C_DIM2)
        if len(quotas) > 3:
            self.text(339, 166, "还有 %d 项" % (len(quotas) - 3), self.f_label, C_DIM2, "e")
        self.draw_quota(quotas, 188)

    def draw_quota(self, quotas, y0):
        if not quotas:
            self.text(17, y0, "36 小时内没有会作废的额度", self.f_tiny, C_DIM2)
            return
        now = datetime.now(TZ8)
        rows = quotas[:3]
        for i, q in enumerate(rows):
            ry = y0 + i * 24
            pct, rst = q["pct"], q["reset"]
            urgent = pct <= 0.001 or (rst and (rst - now).total_seconds() < 3600)
            color = C_BAD if urgent else pct_color(pct)

            nm = q.get("name") or short_name(q["provider"])
            if q.get("n", 1) > 1:
                nm = "%s ×%d" % (nm, q["n"])
            self.text(17, ry, self.fit(nm, self.f_quota, 78), self.f_quota,
                      C_TEXT if pct > 0.001 else C_BAD)

            bx1, bx2, bh = 100, 176, 5
            self.rrect(bx1, ry - bh / 2, bx2, ry + bh / 2, bh / 2, "#242a37")
            if pct > 0.001:
                fw = max(4, (bx2 - bx1) * min(100, pct) / 100.0)
                self.rrect(bx1, ry - bh / 2, bx1 + fw, ry + bh / 2, bh / 2, color)

            self.text(184, ry + 0.5, "%d%%" % int(pct), self.f_tiny, C_DIM)
            cnt = countdown_text(rst) if rst else ("耗尽" if pct <= 0.001 else "—")
            self.text(339, ry + 0.5, cnt, self.f_tiny,
                      color if pct < 50 else C_DIM, "e")


def main():
    import socket
    global _LOCK
    _LOCK = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _LOCK.bind(("127.0.0.1", WIDGET_PORT))
        _LOCK.listen(1)
    except OSError:
        return
    for fn in (lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2),
               lambda: ctypes.windll.user32.SetProcessDPIAware()):
        try:
            fn()
            break
        except Exception:
            pass
    root = tk.Tk()
    Float(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        with open(os.path.join(HERE, "quota_widget.log"), "a", encoding="utf-8") as f:
            f.write("[%s] %r\n" % (datetime.now().strftime("%F %T"), e))
        raise

---
name: magpie-quota-widget
description: 在 Windows 上安装/排障「Magpie 额度浮窗」——一块常驻桌面右下角的小面板，实时显示 Magpie 网关当前调用落在哪个 routing group、用的哪个模型、该模型在强弱榜的名次，以及各平台额度剩余百分比和重置倒计时。当用户说“装个额度浮窗”“我的 Magpie 还剩多少额度看不到”“这个浮窗不显示了”时使用。
---

# Magpie Quota Widget

一个单文件 Python（tkinter，纯标准库）桌面浮窗，只读 Magpie 网关的 HTTP 接口，不写网关、不碰账号、不落盘 token。

## 它读什么

| 用途 | 接口 |
|---|---|
| 各平台额度、重置时间 | `GET {MAGPIE_BASE}/v1/magpie/quotas` |
| 当前调用落在哪个组/模型 | `GET {MAGPIE_BASE}/v1/magpie/route` |
| 可用模型（组名展示） | `GET {MAGPIE_BASE}/v1/models` |
| 近期请求（判断“正在调用”） | `GET {MAGPIE_BASE}/v1/magpie/usage/requests` |
| 强弱榜名次（可选） | 同目录或上一级的 `model_rank.json` |

`MAGPIE_BASE` 默认 `http://127.0.0.1:3425`。

## 安装（Agent 执行顺序）

1. 确认是 Windows（`$env:OS` 或 `uname` 含 MINGW/MSYS）。非 Windows 直接告知不支持，不要硬装。
2. 确认 Magpie 在跑：`curl -s http://127.0.0.1:3425/v1/models`。拿不到就让用户先启动 Magpie。
3. 确认 Python 与 tkinter：
   ```powershell
   python -c "import tkinter; print('ok')"
   ```
   失败则让用户重跑 python.org 安装包并勾选 tcl/tk，不要尝试 pip 安装 tkinter。
4. 在仓库目录执行：
   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```
   它会：找 pythonw → 校验 tkinter → 写开机自启 `%APPDATA%\...\Startup\MagpieQuotaWidget.lnk` → 在桌面生成 `打开额度浮窗.cmd` → 立刻启动守护。
5. 验证：`netstat -ano | findstr :5599` 有 LISTENING，或屏幕上出现面板。
6. 失败看 `quota_widget.log`（仅异常时生成）。

## 手动跑（不走安装脚本）

```powershell
pythonw quota_widget.py          # 单次
pythonw widget_guard.py          # 守护：每 10 秒探一次 5599，挂了自动拉起
```

## 环境变量

| 变量 | 默认 | 作用 |
|---|---|---|
| `MAGPIE_BASE` | `http://127.0.0.1:3425` | 网关地址（远程/容器也行） |
| `QUOTA_WIDGET_PORT` | `5599` | 单实例锁端口；一台机器开多个浮窗时改 |
| `PYTHONW` | 自动 | 指定 pythonw.exe |

## 排障对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 完全看不到窗口 | 存的位置在屏幕外 / 透明度被拉到很低 | 右键不存在的话，删掉 `widget_config.json` 里的 `x`/`y` 或整份文件重开 |
| 面板里没有组 | 网关没有 routing group | 先 `magpie group add` 建组，或用 agent 的默认模型 |
| 数值全是 `—` | 网关没返回 quotas（未登录/额度接口失败） | `magpie accounts` 看登录状态 |
| 启动即退出 | 5599 被占 | `set QUOTA_WIDGET_PORT=5601` 再跑 |
| `import tkinter` 报错 | Python 缺 tcl/tk | 重装 Python，勾 tcl/tk |

## 边界

- 只读。任何“帮我改额度/自动切号”的诉求都不在本 skill 内，改用 magpie 自己的 CLI。
- 不采集遥测、不联网上报；除了本地网关，没有任何出站请求。

# 上传到 GitHub —— 按顺序做，15 分钟

仓库目录（以下命令都在这里跑）：
`magpie-quota-widget`

## 0. 占位符已填好

用户名已填为 `qilijuan82065773-arch`：`LICENSE` 第 3 行、README 的 clone 链接、长文里的仓库链接都已替换，无需再改。

## 1. 装工具（只装一次）

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
```

关掉终端重开一个（让 PATH 生效），然后登录：

```powershell
gh auth login
# 选 GitHub.com → HTTPS → Login with a web browser → 浏览器里确认
```

## 2. 初始化仓库并提交

```powershell
cd "magpie-quota-widget"
git init
git add .
git status        # 确认没有 widget_config.json / *.log 这种本机运行态
git commit -m "feat: Magpie quota widget for Windows desktop"
```

`.gitignore` 已经排除了 `widget_config.json`、`widget_pos.json`、`*.log`、`__pycache__/`，`git status` 里看到它们说明被改过，检查一下再提交。

## 3. 建远程仓库并推上去

```powershell
gh repo create magpie-quota-widget --public --source=. --remote=origin --push
```

这条命令一次干完三件事：建公开仓库、加 `origin`、把 main 推上去。

不想用 gh 也行：网页新建空仓库（**不要**勾 README / .gitignore / license），然后

```powershell
git remote add origin https://github.com/qilijuan82065773-arch/magpie-quota-widget.git
git branch -M main
git push -u origin main
```

## 4. 填仓库门面（决定别人点进来装不装）

在仓库页右上角 **About** 齿轮里填：

- **Description**：`Windows 桌面浮窗 · 实时显示 Magpie 网关在用的模型、强弱名次、各家额度剩余与重置倒计时`
- **Topics**：`magpie` `ai-gateway` `quota` `windows` `tkinter` `python` `llm` `dashboard` `desktop-widget`
- 勾上 **Releases**、**Packages** 按需

**Social preview**：Settings → General → Social preview，上传 `screenshots/panel.png`（1200×630 更好，裁一下即可）。

## 5. 发一个 Release（让"下载即用"成立）

```powershell
git tag -a v1.0.0 -m "v1.0.0 first public release"
git push origin v1.0.0
gh release create v1.0.0 --title "v1.0.0" --notes "首个公开版本：实时组/模型/名次/额度/重置倒计时；DPI 自适应；守护自愈；一键安装脚本。"
```

想附带 zip（不装 git 的人也能下）：

```powershell
Compress-Archive -Path .\* -DestinationPath .\magpie-quota-widget-v1.0.0.zip -Force
gh release upload v1.0.0 .\magpie-quota-widget-v1.0.0.zip
```

## 6. 以后改代码怎么更新

```powershell
git add -A
git commit -m "fix: 坐标越界自愈"
git push
```

发新版就打新 tag 再 `gh release create`。

## 7. 发推之前的三件事

1. 打开仓库的 **匿名窗口** 看一遍：README 首图能不能正常显示（路径是相对路径 `screenshots/panel.png`，必须真的提交进仓库）。
2. 检查 `docs/x-longpost-zh.md` 里的仓库链接，点开能到仓库。
3. X 上贴图用 `screenshots/panel.png` 和 `screenshots/menu.png` 原图，别截图里带桌面背景。

## 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `gh: command not found` | 装了没重开终端 | 重开 PowerShell |
| push 要密码 | GitHub 已停用密码认证 | 用 `gh auth login`，或建 Personal Access Token 当密码 |
| README 图片 404 | `screenshots/` 没提交 | `git add screenshots && git commit` |
| 中文乱码 | git 未设 UTF-8 | `git config --global i18n.commitEncoding utf-8` |
| 提交里混进日志 | `.gitignore` 生效前已 add | `git rm --cached quota_widget.log` |

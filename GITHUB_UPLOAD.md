# 第一次把「屏幕解答」发到 GitHub

这份指南按“第一次做开源”的顺序写。推荐用 **GitHub Desktop**，不需要先学命令行。

> 这台机器目前没有安装 `git`，所以最省事的是 GitHub Desktop。项目目录里还有一个 `ScreenAnswer-source.zip`，它不含 `config.json`、`logs/`、`.venv/`、`dist/`，可以解压后作为干净的源码目录使用。
>
> 上传前把 README 里的 `<your-name>` 换成你的 GitHub 用户名。

---

## 0. 上传前必须确认的事

这个目录里有一个 `config.json`，里面保存着**你的 API Key**（DPAPI 加密，但仍然不能上传）。

`.gitignore` 已经排除了：

```
config.json
test_config.json
logs/
.venv/
dist/
*.zip
build/
__pycache__/
```

上传前请确认这些问题：

- [ ] `config.json` 不在待提交文件里
- [ ] `logs/` 不在待提交文件里
- [ ] `.venv/` 不在待提交文件里
- [ ] `dist/` 和 `ScreenAnswer-win64.zip` 不在待提交文件里
- [ ] 代码里没有写死任何 API Key
- [ ] README 里没有你自己的私人 DeepSeek 会话链接
- [ ] `LICENSE` 里的版权人改成你的名字或项目名（可选）
- [ ] 不要把整个文件夹直接拖进 GitHub 网页上传（容易把 `.venv/`、`config.json` 一起传上去）；用 GitHub Desktop，或解压 `ScreenAnswer-source.zip` 后再操作

> 如果 Key 已经不小心提交到公开仓库：立刻去服务商控制台**删除/重置 Key**，然后重新生成一个。只删文件不够，Git 历史里仍然可以找到。

---

## 方式一：GitHub Desktop（推荐）

### 1. 安装

下载并安装 [GitHub Desktop](https://desktop.github.com/)，登录你的 GitHub 账号。

### 2. 添加本地项目

1. 打开 GitHub Desktop。
2. 菜单 **File → Add local repository**。
3. 选择这个文件夹：
   `D:\4\肥鱼工作区\ScreenAnswer`
4. 如果提示“not a Git repository”，点 **create a repository** / **initialize a repository here**。
5. 默认分支选 `main`。

### 3. 检查要提交的文件

左侧点 **Changes**，确认列表里**没有**：

- `config.json`
- `logs/`
- `.venv/`
- `dist/`
- 任何 `.zip`

如果出现了，先检查 `.gitignore` 是否在这个目录，并且不要勾选它们。

### 4. 第一次提交

在左下角 Summary 填：

```
Initial release v1.0.6
```

点 **Commit to main**。

### 5. 发布到 GitHub

1. 点上方 **Publish repository**。
2. Name 填：`screen-answer`
3. Description 可以填：
   `Windows screen OCR + AI answer overlay. Local OCR, OpenAI-compatible models, no auto-clicking.`
4. 如果要公开，**取消勾选** “Keep this code private”。
5. 点 **Publish repository**。

### 6. 创建 Release（让用户下载 exe）

1. 在项目目录运行 `build.bat`，生成：
   - `dist\ScreenAnswer\ScreenAnswer.exe`
   - `ScreenAnswer-win64.zip`
2. 打开 GitHub 仓库页面 → 右侧 **Releases** → **Create a new release**。
3. Tag 填 `v1.0.6`，标题填 `v1.0.6`。
4. 把 `ScreenAnswer-win64.zip` 拖进附件区域。
5. 写更新说明：

```markdown
首个公开版本。

- Windows 本地 OCR，每 5 秒检查屏幕
- 只在新题目出现时调用模型
- 支持 DeepSeek / 通义千问 / 智谱 / Kimi / OpenAI / Ollama
- 修复换题后不识别、热键冲突、单实例误判等问题
```

6. 点 **Publish release**。

### 7. 设置仓库信息

在仓库页面点右上角 **⚙ / Settings**：

- Description：
  `Windows screen OCR + AI answer overlay. Local OCR, OpenAI-compatible models, no auto-clicking.`
- Topics：
  `windows`, `ocr`, `tkinter`, `deepseek`, `openai`, `screen-capture`, `python`
- 确认 Issues 开启。

---

## 方式二：命令行

### 1. 安装 Git

下载 [Git for Windows](https://git-scm.com/download/win)，安装时保持默认选项即可。安装后重新打开终端。

检查：

```bat
git --version
```

### 2. 配置身份

```bat
git config --global user.name "你的名字"
git config --global user.email "你的邮箱"
```

### 3. 初始化并检查

```bat
cd /d D:\4\肥鱼工作区\ScreenAnswer
git init -b main
git status --short
```

`git status` 里**不应该**出现：

```
config.json
logs/
.venv/
dist/
ScreenAnswer-win64.zip
```

如果出现了，先检查 `.gitignore`，不要继续 `git add`。

### 4. 提交

```bat
git add .
git status --short
git commit -m "Initial release v1.0.6"
```

### 5. 在 GitHub 创建空仓库

1. 打开 GitHub → **New repository**。
2. Name：`screen-answer`
3. **不要**勾选 “Add a README file / .gitignore / license”（本地已经有了）。
4. 创建后复制仓库地址，例如：
   `https://github.com/your-name/screen-answer.git`

### 6. 推送

```bat
git remote add origin https://github.com/your-name/screen-answer.git
git branch -M main
git push -u origin main
```

如果弹出登录窗口，按提示登录 GitHub。

### 7. 创建 Release

和上面 GitHub Desktop 的第 6 步一样：运行 `build.bat`，上传 `ScreenAnswer-win64.zip`，tag 用 `v1.0.6`。

---

## 上传后建议再检查一次

打开 GitHub 仓库页面，确认：

- [ ] 仓库根目录能看到 `README.md`、`LICENSE`、`app.py`、`screen_answer/`
- [ ] 看不到 `config.json`
- [ ] 看不到 `logs/`、`.venv/`、`dist/`
- [ ] README 的截图能正常显示
- [ ] Release 里能下载 `ScreenAnswer-win64.zip`
- [ ] Clone 下来的项目可以按 README 运行

---

## 常见问题

### GitHub Desktop 说 “repository not found”

通常是远程地址或权限问题。确认仓库已创建、账号已登录，并且远程 URL 没写错。

### 推送被拒绝（rejected）

如果远程仓库创建时勾选了 README，本地和远程都有提交。最简单：

```bat
git pull --rebase origin main
git push -u origin main
```

### 不小心提交了 config.json

1. 立刻删除/重置 API Key。
2. 从 Git 中移除：

```bat
git rm --cached config.json
git commit -m "Remove local config"
```

3. 如果已经推到公开仓库，仅删除文件不够，Git 历史仍能找回。最省事的做法是**删除仓库重新建一个**，或者用 `git filter-repo` 清理历史。

### exe 太大，能不能直接提交？

不要。`dist/` 和 `.zip` 已在 `.gitignore` 里；exe 通过 **Releases** 附件提供，不放进 Git 历史。

---

## 仓库发布前的最后一步

```bat
run_tests.bat
```

看到 `OK` 再提交。

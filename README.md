# 实时 X 荐股账号监控

> 研究与可视化用途。本文档和本项目不构成投资建议。

## 项目简介

这是一个独立的实时 X 荐股账号监控项目。它可以同时监控**一个或多个** X 账号的新帖，提取正文里的股票 `$SYMBOL`，用大模型翻译成简体中文，写入独立 SQLite 数据库，并在实时新帖翻译后通过邮件通知你。

项目默认使用本地数据库 `data/monitor.sqlite`，不依赖其他项目数据库。历史数据、实时数据、股票符号、原文、中文翻译和原始 JSON 都保存在本项目目录内，便于后续研究、回测和可视化。

## 多账号监控（2026-06 更新）

- **多账号实时监控**：`WATCH_USERNAMES` 逗号分隔多个用户名，自动合成一条 `from:a OR from:b` 规则（共用一条规则，费用不随人数翻倍）。
- **启动邮件按人分组**：每次启动发送一封摘要邮件，每个账号一个分组、各最近 5 条（含中文翻译）。
- **实时邮件**：单条新帖一封邮件（标题带作者）；同批多条新帖合并为一封、按人分组。
- **历史回补按账号配置且可选**：每个账号一个 curl 子目录 `x_curl/<用户名>/`；不建目录就不下载该账号历史，`HISTORY_ENABLED=false` 全局关闭。
- **历史时间范围限制**：`HISTORY_MAX_MONTHS=3` 只回补最近 3 个月（`0` 不限制），命令行可用 `--months N` 覆盖。
- **一键加账号 curl**：`python add_user_curl.py <用户名>` 自动查 userId 并从现有账号克隆 curl 文件。

**添加一个新监控账号的完整步骤**：

```bash
# 1.（可选，要历史才做）克隆 curl
python add_user_curl.py 新用户名

# 2. .env 名单加人
#    WATCH_USERNAMES=aleabitoreddit,新用户名

# 3. 重启 monitor.py，看日志确认规则：
#    Rule active: ... value=from:aleabitoreddit OR from:新用户名
```

## 架构与数据流

历史与离线补漏走免费的 X GraphQL curl 抓取。你从浏览器开发者工具复制带 cookie 的 GraphQL 请求，保存为 curl 文件后，`history.py` 会读取这些文件抓取历史帖、回复和 premium / 超级关注帖。

实时监控走 twitterapi.io WebSocket。WebSocket 只连接 twitterapi.io，不登录、不请求你的 X 账号，因此不碰你的 X 账号 cookie，也没有 X 账号封号或封 IP 风险。实时推送延迟通常可做到亚秒级。

统一数据流：

1. `history.py` 用 X GraphQL curl 免费回补历史和离线缺口。
2. `monitor.py` 用 twitterapi.io WebSocket 监听实时新帖。
3. `extract.py` 提取 `$SYMBOL`。
4. `store.py` 写入 `data/monitor.sqlite`。
5. 实时新帖调用 `translate.py` 翻译成中文并写入 `tweets.text_zh`。
6. 翻译成功后通过 `email_sender.py` 发送邮件。

## 目录结构

- `monitor.py`: 实时 WebSocket 主程序，启动时可先跑一次历史增量同步。
- `history.py`: 历史全量回补和离线补漏，读取 X GraphQL curl 文件。
- `xfetch.py`: 自包含的 X GraphQL curl 解析、翻页、推文规范化逻辑。
- `store.py`: SQLite 连接、建表、写入推文和股票提及、更新翻译。
- `extract.py`: 股票 `$SYMBOL` 提取与 X 时间解析。
- `translate.py`: OpenAI 兼容 Chat Completions 翻译客户端和历史批量翻译 CLI。
- `email_sender.py`: SMTP / STARTTLS 邮件发送。
- `rules.py`: twitterapi.io tweet filter 规则管理。
- `add_user_curl.py`: 给新账号一键克隆 curl 文件（自动查并替换 userId）。
- `notify.py`: 桌面通知、Telegram、Webhook 和终端通知。
- `config.py`: 从 `.env` 加载配置，组装成程序使用的结构。
- `.env.example`: 可提交的配置模板，不含真实密钥。
- `requirements.txt`: Python 依赖。

## 安装

建议使用 Python 虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

本项目用 `.env` 文件管理配置。先复制模板：

```bash
cp .env.example .env
```

然后编辑 `.env`。该文件包含 twitterapi.io key、LLM key、SMTP 密码等敏感信息，已被 `.gitignore` 忽略，切勿提交、上传或分享。

环境变量说明：

| 变量 | 说明 |
|---|---|
| `TWITTERAPI_KEY` | twitterapi.io 的 API key（注册后在控制台获取）。也可用同名系统环境变量覆盖。 |
| `WATCH_USERNAMES` | 要监控的 X 用户名，不带 `@`；多个账号用逗号分隔（兼容旧的 `WATCH_USERNAME`）。 |
| `WATCH_TAG` | twitterapi.io 规则标签，建议用唯一名称。 |
| `WATCH_INTERVAL_SECONDS` | 规则后台检查间隔，默认 `60` 秒。tweet_filter 会按该间隔轮询；空结果也可能产生最低请求费。 |
| `RULE_ID` | 已有规则 ID；首次留空，运行 `python rules.py ensure` 自动创建。 |
| `DB_PATH` | SQLite 路径，默认 `data/monitor.sqlite`（相对模块目录）。 |
| `DEACTIVATE_ON_EXIT` | Ctrl+C 退出时是否停用规则以停止计费。 |
| `HISTORY_ENABLED` | 是否启用历史抓取。设为 `false` 则完全不下载历史，只做实时监控。 |
| `HISTORY_RUN_ON_START` | 启动 `monitor.py` 前是否先跑一次历史增量补漏。 |
| `HISTORY_MODE_ON_START` | 启动时历史模式，通常 `incremental`。 |
| `HISTORY_X_CURL_DIR` | 存放 X GraphQL curl 文件的根目录，默认 `x_curl`（模块内，已 gitignore）。按账号分子目录：`x_curl/<用户名>/UserTweets.curl` 等；没有子目录的账号不下载历史。 |
| `HISTORY_MAX_PAGES` | 每类时间线最大翻页数。 |
| `HISTORY_PAUSE_SECONDS` | 翻页间隔，避免请求过快。 |
| `HISTORY_MAX_MONTHS` | 只回补最近 N 个月的历史（按 30 天/月估算），早于截止时间的不入库、翻页提前停止；`0` 或留空表示不限制。也可用 `python history.py --months N` 临时覆盖。 |
| `LLM_URL` / `LLM_KEY` / `LLM_MODEL` | 任意 OpenAI 兼容 Chat Completions 接口、key、模型名。 |
| `TRANSLATE_ENABLED` | 实时翻译开关。关闭后仍入库和桌面通知，但不翻译、不发翻译邮件。 |
| `EMAIL_ENABLED` | 是否启用邮件。 |
| `EMAIL_SMTP_HOST` / `EMAIL_SMTP_PORT` / `EMAIL_USE_TLS` | SMTP 主机、端口、是否 STARTTLS（Gmail：`smtp.gmail.com` / `587` / `true`）。 |
| `EMAIL_USER` / `EMAIL_PASSWORD` | SMTP 账号与密码。**Gmail 必须用「应用专用密码 App Password」，不是登录密码。** |
| `EMAIL_FROM` | 发件人地址。 |
| `EMAIL_TO` | 收件人；多个用逗号分隔。 |
| `NOTIFY_DESKTOP` / `NOTIFY_SOUND` | macOS 桌面通知与提示音开关。 |
| `NOTIFY_TELEGRAM_ENABLED` / `NOTIFY_TELEGRAM_BOT_TOKEN` / `NOTIFY_TELEGRAM_CHAT_ID` | 可选 Telegram 通知。 |
| `NOTIFY_WEBHOOK_ENABLED` / `NOTIFY_WEBHOOK_URL` | 可选 HTTP webhook。 |

### 各项凭据如何获取

**1. twitterapi.io API key（`TWITTERAPI_KEY`）**

1. 打开 https://twitterapi.io/ 注册并登录。
2. 在控制台（Dashboard）复制你的 API Key。
3. 充值少量额度即可（实时监控单个账号通常每月几美分）。
4. 填入 `.env` 的 `TWITTERAPI_KEY`。

**2. 大模型翻译（`LLM_URL` / `LLM_KEY` / `LLM_MODEL`）**

- 支持任意 OpenAI 兼容的 Chat Completions 接口。
- `LLM_URL`：接口地址，形如 `https://你的服务/v1/chat/completions`。
- `LLM_KEY`：该服务的 API key。
- `LLM_MODEL`：模型名，例如 `claude-opus-4-6`、`gpt-4o` 等。
- 不需要翻译时设 `TRANSLATE_ENABLED=false`，实时帖仍入库和桌面通知，但不翻译、不发翻译邮件。

**3. 邮件（以 Gmail 为例）**

1. 登录 Google 账号，先开启「两步验证」（必须）。
2. 访问 https://myaccount.google.com/apppasswords 生成 16 位「应用专用密码 App Password」。
3. 填入 `.env`：
   - `EMAIL_SMTP_HOST=smtp.gmail.com`、`EMAIL_SMTP_PORT=587`、`EMAIL_USE_TLS=true`
   - `EMAIL_USER` 和 `EMAIL_FROM`：你的 Gmail 地址
   - `EMAIL_PASSWORD`：上一步的 16 位应用专用密码（**不是** Gmail 登录密码）
   - `EMAIL_TO`：收件人，多个用逗号分隔
- 其他邮箱（163 / QQ 等）同理：换成对应 SMTP 主机和端口，密码用邮箱的「授权码」。

**4. 监控目标与规则（`WATCH_USERNAMES` / `RULE_ID`）**

- `WATCH_USERNAMES`：要监控的 X 用户名，不带 `@`；多个账号用逗号分隔，规则会自动拼成 `from:a OR from:b`。
- `RULE_ID` 首次留空。运行 `python rules.py ensure` 会自动创建并激活规则并打印 rule_id；把它填回 `.env` 可复用。

### 准备 X GraphQL curl 文件（可选，按账号）

历史抓取按账号配置：在 `HISTORY_X_CURL_DIR` 下为每个要回补历史的账号建一个与用户名同名的子目录，放入该账号的 curl 文件：

```
x_curl/
  aleabitoreddit/
    UserTweets.curl
    UserTweetsAndReplies.curl
    UserSuperFollowTweets.curl
  另一个账号/
    UserTweets.curl   # 三个文件不必齐全，缺哪个就跳过哪类时间线
```

**历史下载是可选的**：

- 不想给某个账号下载历史 → 不建该账号的子目录即可，实时监控不受影响（该账号数据从开始监控起积累）。
- 完全不下载历史 → 设 `HISTORY_ENABLED=false`。
- 目标账号的 userId 会自动从 curl 文件 URL 中解析，无需手工配置。

**加新账号的快捷方式**：已有一个账号的 curl 后，其余账号一条命令克隆（cookie 通用，自动查并替换 userId）：

```bash
python add_user_curl.py 新账号用户名
```

复制方法：

1. 在 Chrome 登录 X。
2. 打开目标账号主页。
3. 打开 DevTools 的 Network 面板。
4. 刷新页面或滚动时间线。
5. 找到 GraphQL 请求，例如 `UserTweets`、`UserTweetsAndReplies`、`UserSuperFollowTweets`。
6. 右键请求，选择 `Copy` -> `Copy as cURL`。
7. 分别保存到 `x_curl/<该账号用户名>/` 下的对应 `.curl` 文件名。

这些 curl 文件包含登录 cookie 和鉴权 header，切勿提交到 git，切勿公开分享。

## 运行

首次全量回补历史：

```bash
python history.py --all
```

启动实时监控：

```bash
python monitor.py
```

批量翻译历史推文：

```bash
python translate.py --batch 12 --pause 1.0
```

只试翻少量历史推文：

```bash
python translate.py --limit 20
```

管理 twitterapi.io 规则：

```bash
python rules.py list
python rules.py ensure
python rules.py deactivate
```

不用实时监控时建议停用规则：

```bash
python rules.py deactivate
```

## 计费

- 历史回补：免费，走你自己的 X GraphQL curl 和浏览器 cookie。
- premium / 超级关注帖：只有 curl 路径可以获取，twitterapi.io 通常拿不到。
- 实时 WebSocket / tweet_filter：twitterapi.io 会在服务端按 `WATCH_INTERVAL_SECONDS` 检查规则。空结果也可能产生最低请求费；间隔越短，成本越高。默认 `60` 秒是成本和及时性的折中。
- LLM 翻译：按你的模型服务商规则计费。
- 邮件：通常由 SMTP 服务商限制配额，不由本项目计费。

## 停止计费 / 关闭规则

twitterapi.io 的计费发生在服务端：只要规则处于激活状态（`is_effect=1`，ON_AIR），服务端就会按 `WATCH_INTERVAL_SECONDS` 周期检查规则；即使没有新帖，空结果也可能产生最低请求费。这个过程**和本地程序是否在运行无关**，所以「关掉程序」不等于「停止计费」。

停止计费 = 把规则停用（`is_effect=0`）：

```bash
python rules.py deactivate
```

几种情况：

- **正常退出自动停**：`.env` 里设 `DEACTIVATE_ON_EXIT=true` 时，用 `Ctrl+C`（SIGINT）或 `kill <pid>`（SIGTERM）退出会自动停用规则。
- **强杀 / 断电 / 崩溃**（`kill -9`、关机等）：不会自动停用，需事后手动执行上面的命令。
- **确认是否真的停了**：

```bash
python rules.py list   # 看到 is_effect=0 才算真的停止计费
```

> 提示：tweet_filter 是按规则间隔在服务端检查，空结果也可能有最低请求费。需要降低成本时调大 `WATCH_INTERVAL_SECONDS`；需要彻底零计费时执行 `deactivate`。重新使用时运行 `python monitor.py` 或 `python rules.py ensure` 会自动重新激活。

## 注意事项与免责声明

- 同一 twitterapi.io key 同时只能有一个 WebSocket 连接。
- `x_curl` cookie 会过期，抓取失败时需要重新从浏览器复制 curl。
- curl 文件含 cookie，`.env` 含密钥和密码，切勿提交到 git。
- 本项目用于研究、跟踪和可视化，不构成投资建议。
- 股票提及不等于买入、卖出或持有建议。请自行判断风险。

---

# Real-Time X Stock Mention Monitor

> For research and visualization only. This project and document are not investment advice.

## Overview

This is a standalone local project for monitoring stock-related posts from **one or more** X accounts. It watches new X posts, extracts stock `$SYMBOL` mentions, translates posts into Simplified Chinese with an LLM, stores everything in an independent SQLite database, and sends translated real-time posts by email.

The default database is `data/monitor.sqlite`. It does not depend on any external project database. Historical posts, real-time posts, symbols, original text, Chinese translations, and raw JSON are stored inside this project directory for research, backtesting, and visualization.

## Multi-Account Monitoring (2026-06 update)

- **Multiple accounts in real time**: `WATCH_USERNAMES` takes a comma-separated list and builds a single `from:a OR from:b` rule (one rule shared, cost does not scale with account count).
- **Startup digest grouped by account**: one email per start, one section per account with its 5 most recent posts (with Chinese translation).
- **Real-time emails**: one tweet → one email with the author in the subject; multiple tweets in one push → merged into one email grouped by account.
- **Per-account, optional history backfill**: one curl subdirectory per account (`x_curl/<username>/`); no subdirectory means no history for that account, and `HISTORY_ENABLED=false` disables history entirely.
- **History time window**: `HISTORY_MAX_MONTHS=3` backfills only the last 3 months (`0` = unlimited), overridable with `--months N`.
- **One-command curl cloning**: `python add_user_curl.py <username>` looks up the userId and clones curl files from an existing account.

**Steps to add a new account:**

```bash
# 1. (optional, only if you want history) clone curl files
python add_user_curl.py newusername

# 2. add it to WATCH_USERNAMES in .env
#    WATCH_USERNAMES=aleabitoreddit,newusername

# 3. restart monitor.py and check the log:
#    Rule active: ... value=from:aleabitoreddit OR from:newusername
```

## Architecture And Data Flow

Historical backfill uses free X GraphQL curl requests. You copy authenticated GraphQL requests from your browser DevTools and save them as curl files. `history.py` reads those files to fetch historical posts, replies, and premium / Super Follow posts.

Real-time monitoring uses the twitterapi.io WebSocket. The WebSocket connects only to twitterapi.io. It does not log in to your X account and does not use your X cookies, so it does not create X account ban or IP ban risk. Real-time push latency is usually sub-second.

Unified data flow:

1. `history.py` backfills historical and missed posts for free through X GraphQL curl files.
2. `monitor.py` listens for real-time new posts through twitterapi.io WebSocket.
3. `extract.py` extracts `$SYMBOL` mentions.
4. `store.py` writes records into `data/monitor.sqlite`.
5. Real-time posts are translated by `translate.py` and saved to `tweets.text_zh`.
6. Successful real-time translations are sent by email through `email_sender.py`.

## Directory Structure

- `monitor.py`: Real-time WebSocket entrypoint. It can run an incremental history sync before connecting.
- `history.py`: Full historical backfill and offline catch-up from X GraphQL curl files.
- `xfetch.py`: Self-contained X GraphQL curl parsing, pagination, and tweet normalization logic.
- `store.py`: SQLite connection, schema setup, tweet/symbol insertion, and translation updates.
- `extract.py`: `$SYMBOL` extraction and X date parsing.
- `translate.py`: OpenAI-compatible Chat Completions translation client and historical translation CLI.
- `email_sender.py`: SMTP / STARTTLS email sending.
- `rules.py`: twitterapi.io tweet filter rule management.
- `add_user_curl.py`: one-command curl cloning for new accounts (auto userId lookup and replacement).
- `notify.py`: Desktop, Telegram, webhook, and terminal notifications.
- `config.py`: Loads configuration from `.env` into the structure the app uses.
- `.env.example`: Safe configuration template with no real secrets.
- `requirements.txt`: Python dependencies.

## Installation

A Python virtual environment is recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

This project uses a `.env` file for configuration. Copy the template first:

```bash
cp .env.example .env
```

Then edit `.env`. This file contains the twitterapi.io key, LLM key, SMTP password, and other secrets. It is ignored by `.gitignore`. Never commit, upload, or share it.

Environment variables:

| Variable | Description |
|---|---|
| `TWITTERAPI_KEY` | Your twitterapi.io API key (from its dashboard). A real environment variable of the same name overrides the `.env` value. |
| `WATCH_USERNAMES` | The X usernames to monitor, without `@`; separate multiple accounts with commas (legacy `WATCH_USERNAME` still works). |
| `WATCH_TAG` | twitterapi.io rule tag. Use a project-specific unique name. |
| `WATCH_INTERVAL_SECONDS` | Server-side rule check interval. Default `60` seconds. tweet_filter checks on this interval; empty results may still incur the minimum request charge. |
| `RULE_ID` | Existing rule ID. Leave empty on first use; `python rules.py ensure` creates one. |
| `DB_PATH` | SQLite path, default `data/monitor.sqlite` (relative to the module directory). |
| `DEACTIVATE_ON_EXIT` | Whether Ctrl+C deactivates the rule to stop billing. |
| `HISTORY_ENABLED` | Enable historical fetching. Set `false` to skip history entirely (real-time only). |
| `HISTORY_RUN_ON_START` | Run an incremental history catch-up before `monitor.py` connects. |
| `HISTORY_MODE_ON_START` | Startup history mode, usually `incremental`. |
| `HISTORY_X_CURL_DIR` | Root directory of X GraphQL curl files, default `x_curl` (in-module, gitignored). One subdirectory per account: `x_curl/<username>/UserTweets.curl` etc.; accounts without a subdirectory skip history. |
| `HISTORY_MAX_PAGES` | Maximum pages per timeline source. |
| `HISTORY_PAUSE_SECONDS` | Pause between pages to avoid excessive request rate. |
| `HISTORY_MAX_MONTHS` | Only backfill the last N months (approximated as 30 days/month); older tweets are not stored and paging stops early. `0` or empty means unlimited. Override ad hoc with `python history.py --months N`. |
| `LLM_URL` / `LLM_KEY` / `LLM_MODEL` | Any OpenAI-compatible Chat Completions endpoint, key, and model name. |
| `TRANSLATE_ENABLED` | Real-time translation switch. If off, posts are still stored and notified, but not translated/emailed. |
| `EMAIL_ENABLED` | Enable email. |
| `EMAIL_SMTP_HOST` / `EMAIL_SMTP_PORT` / `EMAIL_USE_TLS` | SMTP host, port, STARTTLS (Gmail: `smtp.gmail.com` / `587` / `true`). |
| `EMAIL_USER` / `EMAIL_PASSWORD` | SMTP account and password. **Gmail requires an App Password, not your login password.** |
| `EMAIL_FROM` | Sender address. |
| `EMAIL_TO` | Recipients; separate multiple with commas. |
| `NOTIFY_DESKTOP` / `NOTIFY_SOUND` | macOS desktop notification and sound switches. |
| `NOTIFY_TELEGRAM_ENABLED` / `NOTIFY_TELEGRAM_BOT_TOKEN` / `NOTIFY_TELEGRAM_CHAT_ID` | Optional Telegram notifications. |
| `NOTIFY_WEBHOOK_ENABLED` / `NOTIFY_WEBHOOK_URL` | Optional HTTP webhook. |

### How To Get Each Credential

**1. twitterapi.io API key (`TWITTERAPI_KEY`)**

1. Sign up and log in at https://twitterapi.io/.
2. Copy your API Key from the dashboard.
3. Add a small amount of credit (monitoring one account is usually a few cents per month).
4. Put it in `TWITTERAPI_KEY` in `.env`.

**2. LLM translation (`LLM_URL` / `LLM_KEY` / `LLM_MODEL`)**

- Any OpenAI-compatible Chat Completions API works.
- `LLM_URL`: endpoint such as `https://your-host/v1/chat/completions`.
- `LLM_KEY`: API key for that service.
- `LLM_MODEL`: model name, e.g. `claude-opus-4-6`, `gpt-4o`, etc.
- Set `TRANSLATE_ENABLED=false` to skip translation; posts are still stored and notified.

**3. Email (Gmail example)**

1. Enable 2-Step Verification on your Google account first (required).
2. Generate a 16-character App Password at https://myaccount.google.com/apppasswords.
3. Fill in `.env`:
   - `EMAIL_SMTP_HOST=smtp.gmail.com`, `EMAIL_SMTP_PORT=587`, `EMAIL_USE_TLS=true`
   - `EMAIL_USER` and `EMAIL_FROM`: your Gmail address
   - `EMAIL_PASSWORD`: the 16-character App Password (NOT your Gmail login password)
   - `EMAIL_TO`: recipients, comma-separated for multiple
- Other providers (e.g. Outlook, QQ, 163) work the same way with their SMTP host/port and an app/authorization password.

**4. Watch target and rule (`WATCH_USERNAMES` / `RULE_ID`)**

- `WATCH_USERNAMES`: the X usernames to monitor, without `@`; commas separate multiple accounts and the rule becomes `from:a OR from:b`.
- Leave `RULE_ID` empty at first. Running `python rules.py ensure` creates and activates the rule and prints its rule_id; put it back into `.env` to reuse it.

### Prepare X GraphQL curl files (optional, per account)

Historical fetching is configured per account: create a subdirectory named after each username under `HISTORY_X_CURL_DIR` and put that account's curl files inside:

```
x_curl/
  aleabitoreddit/
    UserTweets.curl
    UserTweetsAndReplies.curl
    UserSuperFollowTweets.curl
  anotheruser/
    UserTweets.curl   # the three files are optional; missing ones are skipped
```

**History download is optional:**

- Skip history for one account → simply don't create its subdirectory; real-time monitoring is unaffected (data accumulates from the moment monitoring starts).
- Skip history entirely → set `HISTORY_ENABLED=false`.
- The target userId is parsed automatically from the curl file URL; no manual configuration needed.

**Shortcut for adding accounts:** once one account's curl files exist, clone them for any other account in one command (cookies are shared; the userId is looked up and replaced automatically):

```bash
python add_user_curl.py <new_username>
```

How to copy them:

1. Log in to X in Chrome.
2. Open the target account page.
3. Open DevTools and go to the Network panel.
4. Refresh the page or scroll the timeline.
5. Find GraphQL requests such as `UserTweets`, `UserTweetsAndReplies`, or `UserSuperFollowTweets`.
6. Right-click the request and choose `Copy` -> `Copy as cURL`.
7. Save each request under `x_curl/<username>/` using the file names above.

These curl files contain login cookies and auth headers. Never commit or share them.

## Usage

Run the first full historical backfill:

```bash
python history.py --all
```

Start real-time monitoring:

```bash
python monitor.py
```

Batch-translate historical posts:

```bash
python translate.py --batch 12 --pause 1.0
```

Translate only a small sample:

```bash
python translate.py --limit 20
```

Manage twitterapi.io rules:

```bash
python rules.py list
python rules.py ensure
python rules.py deactivate
```

Deactivate the rule when you are not using real-time monitoring:

```bash
python rules.py deactivate
```

## Costs

- Historical backfill: free, using your own X GraphQL curl requests and browser cookies.
- Premium / Super Follow posts: available only through the curl path; twitterapi.io usually cannot fetch them.
- Real-time WebSocket / tweet_filter: twitterapi.io checks the rule server-side at `WATCH_INTERVAL_SECONDS`. Empty results may still incur the minimum request charge; shorter intervals cost more. The default `60` seconds balances cost and timeliness.
- LLM translation: charged by your model provider.
- Email: usually subject to SMTP provider quota, not charged by this project.

## Stop Billing / Deactivate The Rule

twitterapi.io billing happens server-side: as long as the rule is active (`is_effect=1`, ON_AIR), the service checks the rule at `WATCH_INTERVAL_SECONDS`. Empty results may still incur the minimum request charge, **regardless of whether the local program is running**. So "closing the program" is NOT the same as "stopping billing".

Stop billing = deactivate the rule (`is_effect=0`):

```bash
python rules.py deactivate
```

Cases:

- **Auto-stop on normal exit**: when `DEACTIVATE_ON_EXIT=true` in `.env`, exiting with `Ctrl+C` (SIGINT) or `kill <pid>` (SIGTERM) deactivates the rule automatically.
- **Hard kill / power loss / crash** (`kill -9`, shutdown, etc.): will NOT auto-deactivate; run the command above afterwards.
- **Confirm it actually stopped**:

```bash
python rules.py list   # is_effect=0 means billing is really stopped
```

> Note: tweet_filter checks server-side on the configured interval, and empty results may still have a minimum request charge. Increase `WATCH_INTERVAL_SECONDS` to reduce cost. Deactivate when you want zero billing. Running `python monitor.py` or `python rules.py ensure` re-activates it.

## Notes And Disclaimer

- A single twitterapi.io key can have only one active WebSocket connection at a time.
- `x_curl` cookies expire. Copy fresh curl commands from your browser when historical fetching fails.
- curl files contain cookies, and `.env` contains secrets and passwords. Never commit them to git.
- This project is for research, tracking, and visualization only. It is not investment advice.
- Stock mentions are not buy, sell, or hold recommendations. Evaluate risks independently.

# 实时 X 荐股账号监控

> 研究与可视化用途。本文档和本项目不构成投资建议。

## 项目简介

这是一个独立的实时 X 荐股账号监控项目。它可以监控某个 X 账号的新帖，提取正文里的股票 `$SYMBOL`，用大模型翻译成简体中文，写入独立 SQLite 数据库，并在实时新帖翻译后通过邮件通知你。

项目默认使用本地数据库 `data/monitor.sqlite`，不依赖其他项目数据库。历史数据、实时数据、股票符号、原文、中文翻译和原始 JSON 都保存在本项目目录内，便于后续研究、回测和可视化。

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
- `notify.py`: 桌面通知、Telegram、Webhook 和终端通知。
- `config.py`: 加载 `config.json`，支持环境变量覆盖 API key。
- `config.example.json`: 可提交的配置模板，不含真实密钥。
- `requirements.txt`: Python 依赖。

## 安装

建议使用 Python 虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

先复制模板：

```bash
cp config.example.json config.json
```

然后编辑 `config.json`。`config.json` 会包含 API key、LLM key、SMTP 密码和 X cookie 文件路径，已经被 `.gitignore` 忽略。切勿提交、上传或分享该文件。

### `api_key`

twitterapi.io 的 API key。注册 twitterapi.io 后在控制台获取。

示例：

```json
"api_key": "YOUR_TWITTERAPI_IO_KEY"
```

也可以用环境变量覆盖：

```bash
export TWITTERAPI_KEY="YOUR_TWITTERAPI_IO_KEY"
```

### `watch`

要监控的 X 账号和 filter rule 参数：

```json
"watch": {
  "username": "TARGET_X_USERNAME",
  "tag": "my_stock_watch",
  "interval_seconds": 0.1
}
```

- `username`: X 用户名，不带 `@`。
- `tag`: twitterapi.io 规则标签，建议用项目唯一名称。
- `interval_seconds`: twitterapi.io 规则间隔。保守使用默认值即可。

### `rule_id`

已存在的 twitterapi.io rule ID。首次使用可以留空，然后运行：

```bash
python rules.py ensure
```

程序会按 `watch.username` 和 `watch.tag` 创建或激活规则。

### `db_path`

SQLite 数据库路径：

```json
"db_path": "data/monitor.sqlite"
```

相对路径按项目目录解析。默认会自动创建 `data/monitor.sqlite`。

### `history`

历史回补配置：

```json
"history": {
  "enabled": true,
  "run_on_start": true,
  "mode_on_start": "incremental",
  "x_curl_dir": "../x_curl",
  "max_pages": 200,
  "pause_seconds": 0.8
}
```

- `enabled`: 是否启用历史抓取。
- `run_on_start`: 启动 `monitor.py` 前是否先跑一次历史增量补漏。
- `mode_on_start`: 启动时历史模式，通常用 `incremental`。
- `x_curl_dir`: 存放 X GraphQL curl 文件的目录。
- `max_pages`: 每类时间线最多翻页数。
- `pause_seconds`: 翻页间隔，避免请求过快。

需要准备三个 curl 文件：

- `UserTweets.curl`
- `UserTweetsAndReplies.curl`
- `UserSuperFollowTweets.curl`

复制方法：

1. 在 Chrome 登录 X。
2. 打开目标账号主页。
3. 打开 DevTools 的 Network 面板。
4. 刷新页面或滚动时间线。
5. 找到 GraphQL 请求，例如 `UserTweets`、`UserTweetsAndReplies`、`UserSuperFollowTweets`。
6. 右键请求，选择 `Copy` -> `Copy as cURL`。
7. 分别保存为上面的 `.curl` 文件名。

这些 curl 文件包含登录 cookie 和鉴权 header，切勿提交到 git，切勿公开分享。

### `llm`

任意 OpenAI 兼容 Chat Completions 接口：

```json
"llm": {
  "url": "https://YOUR_LLM_HOST/v1/chat/completions",
  "key": "YOUR_LLM_API_KEY",
  "model": "YOUR_MODEL_NAME"
}
```

- `url`: Chat Completions endpoint。
- `key`: LLM API key。
- `model`: 模型名。

### `translate`

实时翻译开关：

```json
"translate": {
  "enabled": true
}
```

关闭后实时新帖仍会入库和桌面通知，但不会调用 LLM 翻译，也不会发送翻译邮件。

### `email`

SMTP 邮件配置：

```json
"email": {
  "enabled": true,
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "use_tls": true,
  "user": "YOUR_EMAIL_ACCOUNT",
  "password": "YOUR_EMAIL_APP_PASSWORD",
  "from": "YOUR_FROM_EMAIL",
  "to": ["YOUR_TO_EMAIL_1", "YOUR_TO_EMAIL_2"]
}
```

Gmail 示例说明：

- `smtp_host`: `smtp.gmail.com`
- `smtp_port`: `587`
- `use_tls`: `true`
- `password`: 使用 Gmail App Password / 应用专用密码，不是 Gmail 登录密码。

如果邮件发送失败，程序只打印 warning，不会中断实时监控。

### `notify`

本地和外部通知配置：

```json
"notify": {
  "desktop": true,
  "sound": true,
  "telegram": {
    "enabled": false,
    "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
    "chat_id": "YOUR_CHAT_ID"
  },
  "webhook": {
    "enabled": false,
    "url": "YOUR_WEBHOOK_URL"
  }
}
```

- `desktop`: macOS 桌面通知。
- `sound`: 桌面通知声音。
- `telegram`: 可选 Telegram 通知。
- `webhook`: 可选 HTTP webhook。

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
- 实时 WebSocket：twitterapi.io 按匹配到的 tweet 计费；只监控少量账号时成本通常很低。
- LLM 翻译：按你的模型服务商规则计费。
- 邮件：通常由 SMTP 服务商限制配额，不由本项目计费。

## 注意事项与免责声明

- 同一 twitterapi.io key 同时只能有一个 WebSocket 连接。
- `x_curl` cookie 会过期，抓取失败时需要重新从浏览器复制 curl。
- curl 文件含 cookie，`config.json` 含密钥和密码，切勿提交到 git。
- 本项目用于研究、跟踪和可视化，不构成投资建议。
- 股票提及不等于买入、卖出或持有建议。请自行判断风险。

---

# Real-Time X Stock Mention Monitor

> For research and visualization only. This project and document are not investment advice.

## Overview

This is a standalone local project for monitoring stock-related posts from a selected X account. It watches new X posts, extracts stock `$SYMBOL` mentions, translates posts into Simplified Chinese with an LLM, stores everything in an independent SQLite database, and sends translated real-time posts by email.

The default database is `data/monitor.sqlite`. It does not depend on any external project database. Historical posts, real-time posts, symbols, original text, Chinese translations, and raw JSON are stored inside this project directory for research, backtesting, and visualization.

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
- `notify.py`: Desktop, Telegram, webhook, and terminal notifications.
- `config.py`: Loads `config.json` and supports API key override by environment variable.
- `config.example.json`: Safe configuration template with no real secrets.
- `requirements.txt`: Python dependencies.

## Installation

A Python virtual environment is recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy the template first:

```bash
cp config.example.json config.json
```

Then edit `config.json`. This file contains API keys, LLM keys, SMTP passwords, and X curl file paths. It is ignored by `.gitignore`. Never commit, upload, or share it.

### `api_key`

Your twitterapi.io API key. Register on twitterapi.io and copy the key from its dashboard.

Example:

```json
"api_key": "YOUR_TWITTERAPI_IO_KEY"
```

You can also override it with an environment variable:

```bash
export TWITTERAPI_KEY="YOUR_TWITTERAPI_IO_KEY"
```

### `watch`

The X account and filter rule parameters:

```json
"watch": {
  "username": "TARGET_X_USERNAME",
  "tag": "my_stock_watch",
  "interval_seconds": 0.1
}
```

- `username`: X username without `@`.
- `tag`: twitterapi.io rule tag. Use a project-specific unique name.
- `interval_seconds`: twitterapi.io rule interval. The default is usually fine.

### `rule_id`

An existing twitterapi.io rule ID. You may leave it empty on first use, then run:

```bash
python rules.py ensure
```

The script will create or activate a rule based on `watch.username` and `watch.tag`.

### `db_path`

SQLite database path:

```json
"db_path": "data/monitor.sqlite"
```

Relative paths are resolved from this project directory. `data/monitor.sqlite` is created automatically by default.

### `history`

Historical backfill configuration:

```json
"history": {
  "enabled": true,
  "run_on_start": true,
  "mode_on_start": "incremental",
  "x_curl_dir": "../x_curl",
  "max_pages": 200,
  "pause_seconds": 0.8
}
```

- `enabled`: Enable historical fetching.
- `run_on_start`: Run an incremental history catch-up before `monitor.py` connects to WebSocket.
- `mode_on_start`: Startup history mode. Usually `incremental`.
- `x_curl_dir`: Directory containing X GraphQL curl files.
- `max_pages`: Maximum pages per timeline source.
- `pause_seconds`: Pause between pages to avoid excessive request rate.

You need three curl files:

- `UserTweets.curl`
- `UserTweetsAndReplies.curl`
- `UserSuperFollowTweets.curl`

How to copy them:

1. Log in to X in Chrome.
2. Open the target account page.
3. Open DevTools and go to the Network panel.
4. Refresh the page or scroll the timeline.
5. Find GraphQL requests such as `UserTweets`, `UserTweetsAndReplies`, or `UserSuperFollowTweets`.
6. Right-click the request and choose `Copy` -> `Copy as cURL`.
7. Save each request using the file names above.

These curl files contain login cookies and auth headers. Never commit or share them.

### `llm`

Any OpenAI-compatible Chat Completions API:

```json
"llm": {
  "url": "https://YOUR_LLM_HOST/v1/chat/completions",
  "key": "YOUR_LLM_API_KEY",
  "model": "YOUR_MODEL_NAME"
}
```

- `url`: Chat Completions endpoint.
- `key`: LLM API key.
- `model`: Model name.

### `translate`

Real-time translation switch:

```json
"translate": {
  "enabled": true
}
```

If disabled, real-time posts are still stored and desktop notifications still work, but no LLM translation or translated email will be sent.

### `email`

SMTP email configuration:

```json
"email": {
  "enabled": true,
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "use_tls": true,
  "user": "YOUR_EMAIL_ACCOUNT",
  "password": "YOUR_EMAIL_APP_PASSWORD",
  "from": "YOUR_FROM_EMAIL",
  "to": ["YOUR_TO_EMAIL_1", "YOUR_TO_EMAIL_2"]
}
```

Gmail notes:

- `smtp_host`: `smtp.gmail.com`
- `smtp_port`: `587`
- `use_tls`: `true`
- `password`: use a Gmail App Password, not your normal Gmail login password.

If email sending fails, the program prints a warning and keeps the real-time monitor running.

### `notify`

Local and external notification settings:

```json
"notify": {
  "desktop": true,
  "sound": true,
  "telegram": {
    "enabled": false,
    "bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
    "chat_id": "YOUR_CHAT_ID"
  },
  "webhook": {
    "enabled": false,
    "url": "YOUR_WEBHOOK_URL"
  }
}
```

- `desktop`: macOS desktop notifications.
- `sound`: Desktop notification sound.
- `telegram`: Optional Telegram notifications.
- `webhook`: Optional HTTP webhook.

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
- Real-time WebSocket: twitterapi.io charges by matched tweet. Monitoring a small number of accounts is usually low cost.
- LLM translation: charged by your model provider.
- Email: usually subject to SMTP provider quota, not charged by this project.

## Notes And Disclaimer

- A single twitterapi.io key can have only one active WebSocket connection at a time.
- `x_curl` cookies expire. Copy fresh curl commands from your browser when historical fetching fails.
- curl files contain cookies, and `config.json` contains secrets and passwords. Never commit them to git.
- This project is for research, tracking, and visualization only. It is not investment advice.
- Stock mentions are not buy, sell, or hold recommendations. Evaluate risks independently.

import importlib
import html
import json
import signal
import sys

import websocket

import history
from config import load_config
from email_sender import send_email
from notify import notify
from rules import RuleManager
from store import get_translation, load_recent_main_tweets, normalize_tweet, save_tweet, update_translation


translate_module = importlib.import_module("translate")
translate_text = translate_module.translate_text


WS_URL = "wss://ws.twitterapi.io/twitter/tweet/websocket"
STARTUP_BATCH_SIZE = 20
SYMBOL_NAMES = {
    "AAOI": "Applied Optoelectronics",
    "AAPL": "Apple",
    "AMAT": "Applied Materials",
    "AMD": "Advanced Micro Devices",
    "AMZN": "Amazon",
    "ANET": "Arista Networks",
    "ARM": "Arm Holdings",
    "ASML": "ASML Holding",
    "AVGO": "Broadcom",
    "AXTI": "AXT",
    "COHR": "Coherent",
    "DELL": "Dell Technologies",
    "EWY": "iShares MSCI South Korea ETF",
    "GOOGL": "Alphabet",
    "HPE": "Hewlett Packard Enterprise",
    "INTC": "Intel",
    "IONQ": "IonQ",
    "JBL": "Jabil",
    "KLAC": "KLA",
    "LITE": "Lumentum",
    "LRCX": "Lam Research",
    "META": "Meta Platforms",
    "MRVL": "Marvell Technology",
    "MSFT": "Microsoft",
    "MU": "Micron Technology",
    "NBIS": "Nebius Group",
    "NVDA": "NVIDIA",
    "ORCL": "Oracle",
    "POET": "POET Technologies",
    "QCOM": "Qualcomm",
    "RDDT": "Reddit",
    "SIVE": "Sivers Semiconductors",
    "SMCI": "Super Micro Computer",
    "SNDK": "SanDisk",
    "SOI": "Soitec",
    "STX": "Seagate Technology",
    "TSLA": "Tesla",
    "TSM": "Taiwan Semiconductor Manufacturing",
    "TSEM": "Tower Semiconductor",
    "WDC": "Western Digital",
}


class Monitor:
    def __init__(self):
        self.config = load_config()
        self.rule_id = None
        self.processed_ids = set()
        self.ws = None
        self._shutting_down = False
        self._startup_batch_handled = False

    def run(self):
        self._activate_rule()
        self._run_history()
        self._send_startup_digest_from_db()
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)
        self.ws = websocket.WebSocketApp(
            WS_URL,
            header=[f"x-api-key: {self.config['api_key']}"],
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self.ws.run_forever(ping_interval=40, ping_timeout=30, reconnect=90)

    def _run_history(self):
        settings = self.config.get("history") or {}
        if not settings.get("enabled") or not settings.get("run_on_start"):
            return
        try:
            mode = settings.get("mode_on_start") or "incremental"
            result = history.run_history(
                mode,
                x_curl_dir=settings.get("x_curl_dir"),
                max_pages=int(settings.get("max_pages", 200)),
                pause=float(settings.get("pause_seconds", 0.8)),
            )
            print(f"History complete: {result}")
        except Exception as exc:
            print(f"history skipped: {exc}")

    def _activate_rule(self):
        watch = self.config["watch"]
        value = f"from:{watch['username']}"
        manager = RuleManager(self.config["api_key"])
        self.rule_id = manager.ensure_active(watch["tag"], value, watch["interval_seconds"])
        print(f"Rule active: {self.rule_id} tag={watch['tag']} value={value}")

    def _on_open(self, ws):
        print("WebSocket connected.")

    def _on_message(self, ws, message):
        try:
            event = json.loads(message)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON message: {exc}")
            return

        event_type = event.get("event_type")
        if event_type in {"connected", "ping"}:
            print(f"event={event_type}")
            return

        if event_type == "tweet":
            tweets = event.get("tweets") or []
            if self._is_startup_batch(tweets):
                self._handle_startup_batch(tweets, event_type)
                return
            for tweet in tweets:
                self._handle_tweet(tweet, event_type)
            return

        if event_type == "fast_tweet":
            self._handle_tweet(event.get("tweet") or {}, event_type)
            return

        print(f"Unhandled event_type={event_type}")

    def _handle_tweet(self, raw_tweet, event_type):
        tweet = normalize_tweet(raw_tweet, event_type)
        tweet_id = tweet.get("tweet_id")
        if not tweet_id or tweet_id in self.processed_ids:
            return

        self.processed_ids.add(tweet_id)
        is_new, symbols = save_tweet(tweet)
        if tweet.get("snow_delay_ms") is not None:
            print(f"tweet_id={tweet_id} snow_delay_ms={tweet['snow_delay_ms']}")

        if not is_new:
            print(f"duplicate tweet_id={tweet_id}")
            return
        if tweet.get("is_reply"):
            print(f"reply skipped tweet_id={tweet_id}")
            return

        username = tweet.get("author_screen_name") or self.config["watch"]["username"]
        zh = translate_text(tweet.get("text") or "")
        if zh:
            update_translation(tweet_id, zh)
            self._send_realtime_email(username, symbols, tweet, zh)

        title = f"🔔 ${username} 新帖"
        symbol_text = _format_symbols_text(symbols)
        body = f"{symbol_text}\n{(tweet.get('text') or '')[:200]}"
        notify(title, body, tweet.get("url"), sound=self.config.get("notify", {}).get("sound", True))

    def _is_startup_batch(self, tweets):
        if self._startup_batch_handled or len(tweets) < STARTUP_BATCH_SIZE:
            return False
        self._startup_batch_handled = True
        return True

    def _send_startup_digest_from_db(self):
        rows = load_recent_main_tweets(STARTUP_BATCH_SIZE)
        if not rows:
            return
        items = []
        for index, row in enumerate(rows, start=1):
            items.append(
                {
                    "index": index,
                    "tweet": row["tweet"],
                    "symbols": row["symbols"],
                    "translation": row["translation"],
                    "is_new": False,
                }
            )
        self._translate_startup_items(items)
        self._send_startup_batch_email(items, len(items))
        self._startup_batch_handled = True

    def _handle_startup_batch(self, raw_tweets, event_type):
        items = []
        for index, raw_tweet in enumerate(raw_tweets, start=1):
            tweet = normalize_tweet(raw_tweet, event_type)
            tweet_id = tweet.get("tweet_id")
            if not tweet_id or tweet_id in self.processed_ids:
                continue

            self.processed_ids.add(tweet_id)
            is_new, symbols = save_tweet(tweet)
            if not is_new:
                print(f"duplicate tweet_id={tweet_id}")
            if tweet.get("is_reply"):
                print(f"reply skipped tweet_id={tweet_id}")
                continue

            items.append(
                {
                    "index": index,
                    "tweet": tweet,
                    "symbols": symbols,
                    "translation": get_translation(tweet_id) or "",
                    "is_new": is_new,
                }
            )

        self._translate_startup_items(items)
        self._send_startup_batch_email(items, len(raw_tweets))

    def _translate_startup_items(self, items):
        pending = [item for item in items if not item["translation"]]
        if not pending:
            return

        head = (
            "你是金融/半导体领域的中英翻译。把下面每一条英文推文翻成自然流畅的简体中文。"
            "保留 $股票代码、数字、公司/产品专名不译，术语用业内译法（CPO=共封装光学、InP=磷化铟、HBM 保留等）。\n"
            "输出格式：对每条，先单独一行写 @@@该条的id@@@，下一行起写中文译文（可多行），再写下一条。"
            "除此之外不要输出任何多余文字或代码块标记。\n\n"
        )
        body = "".join(f"@@@{item['tweet']['tweet_id']}@@@\n{item['tweet']['text']}\n\n" for item in pending)
        try:
            translated = translate_module.parse_marked(translate_module.chat(head + body))
        except Exception as exc:
            print(f"startup batch translate warning: {exc}")
            return

        for item in pending:
            tweet_id = item["tweet"]["tweet_id"]
            zh = translated.get(str(tweet_id))
            if zh:
                item["translation"] = zh
                update_translation(tweet_id, zh)

    def _send_startup_batch_email(self, items, raw_count):
        watch = self.config["watch"]
        subject = f"监控已启动 @{watch['username']} 最近{raw_count}条"
        header = (
            f"监控账号：@{watch['username']}\n"
            f"规则标签：{watch['tag']}\n"
            f"规则 ID：{self.rule_id or '-'}\n"
            f"检查间隔：{watch['interval_seconds']} 秒\n"
            f"启动批量推送：{raw_count} 条\n"
            f"本邮件包含：{len(items)} 条\n"
        )
        sections = [header]
        for item in items:
            tweet = item["tweet"]
            symbol_text = _format_symbols_text(item["symbols"])
            status = "新入库" if item["is_new"] else "数据库已存在"
            sections.append(
                "\n"
                f"--- #{item['index']} {symbol_text} / {status} ---\n"
                f"时间：{tweet.get('created_at') or '-'}\n"
                f"原帖：{tweet.get('url') or ''}\n"
                f"【中文翻译】\n{item['translation'] or '（翻译失败，保留原文）'}\n\n"
                f"【原文】\n{tweet.get('text') or ''}\n"
            )
        body_text = "\n".join(sections)
        send_email(subject, body_text, body_html=self._startup_batch_html(subject, items, raw_count))

    def _startup_batch_html(self, subject, items, raw_count):
        watch = self.config["watch"]
        cards = []
        for item in items:
            tweet = item["tweet"]
            symbols = item["symbols"]
            symbol_html = "".join(
                f"<span class=\"tag\">{html.escape(_format_symbol_label(symbol))}</span>" for symbol in symbols
            )
            if not symbol_html:
                symbol_html = "<span class=\"tag muted\">无股票符号</span>"
            status = "新入库" if item["is_new"] else "数据库已存在"
            cards.append(
                f"""
                <article class="tweet-card">
                    <div class="card-head">
                        <div>
                            <div class="card-kicker">#{item['index']} · {html.escape(status)}</div>
                            <h2>{symbol_html}</h2>
                        </div>
                        <a class="open-link" href="{html.escape(tweet.get('url') or '')}">打开原帖</a>
                    </div>
                    <div class="meta">时间：{html.escape(tweet.get('created_at') or '-')}</div>
                    <section class="translation">
                        <h3>中文翻译</h3>
                        <p>{html.escape(item['translation'] or '（翻译失败，保留原文）').replace(chr(10), '<br>')}</p>
                    </section>
                    <section class="original">
                        <h3>原文</h3>
                        <p>{html.escape(tweet.get('text') or '').replace(chr(10), '<br>')}</p>
                    </section>
                </article>
                """
            )

        return f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    background: #0b1020;
                    color: #172033;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
                    line-height: 1.58;
                    font-size: 14px;
                }}
                .email-bg {{ width: 100%; background: #0b1020; padding: 24px 0; }}
                .shell {{
                    max-width: 920px;
                    margin: 0 auto;
                    background: #f8fafc;
                    border: 1px solid #27324a;
                    border-radius: 14px;
                    overflow: hidden;
                }}
                .hero {{
                    background: #10182c;
                    color: #ffffff;
                    padding: 30px 34px 26px;
                }}
                .brand {{
                    color: #67e8f9;
                    font-size: 12px;
                    font-weight: 700;
                    letter-spacing: 0.14em;
                    text-transform: uppercase;
                    margin-bottom: 12px;
                }}
                h1 {{ margin: 0; font-size: 28px; line-height: 1.2; color: #ffffff; }}
                .summary {{
                    display: block;
                    margin-top: 16px;
                    color: #cbd5e1;
                }}
                .content {{ padding: 26px 30px 32px; }}
                .tweet-card {{
                    background: #ffffff;
                    border: 1px solid #d8e1ed;
                    border-radius: 10px;
                    padding: 18px 20px;
                    margin-bottom: 16px;
                }}
                .card-head {{
                    display: flex;
                    justify-content: space-between;
                    gap: 16px;
                    align-items: flex-start;
                    border-bottom: 1px solid #e5edf5;
                    padding-bottom: 12px;
                    margin-bottom: 12px;
                }}
                .card-kicker {{
                    color: #64748b;
                    font-size: 12px;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.08em;
                    margin-bottom: 8px;
                }}
                h2 {{ margin: 0; font-size: 17px; line-height: 1.4; }}
                h3 {{
                    margin: 14px 0 6px;
                    font-size: 14px;
                    color: #0f172a;
                    border-left: 4px solid #14b8a6;
                    padding-left: 8px;
                }}
                p {{ margin: 0; }}
                .tag {{
                    display: inline-block;
                    padding: 3px 8px;
                    margin: 0 6px 6px 0;
                    border-radius: 999px;
                    background: #dff7f2;
                    color: #0f766e;
                    font-weight: 800;
                    font-size: 13px;
                }}
                .tag.muted {{ background: #e2e8f0; color: #475569; }}
                .open-link {{
                    color: #2563eb;
                    text-decoration: none;
                    white-space: nowrap;
                    font-weight: 700;
                    font-size: 13px;
                }}
                .meta {{ color: #64748b; font-size: 13px; margin-bottom: 10px; }}
                .translation {{
                    background: #f0fdfa;
                    border: 1px solid #b6ece4;
                    border-radius: 8px;
                    padding: 12px 14px;
                    margin-bottom: 10px;
                }}
                .original {{
                    color: #475569;
                    background: #f8fafc;
                    border: 1px solid #e2e8f0;
                    border-radius: 8px;
                    padding: 12px 14px;
                }}
                .footer {{
                    padding: 16px 30px 24px;
                    color: #64748b;
                    font-size: 12px;
                    background: #eef2f7;
                    border-top: 1px solid #d6dee9;
                }}
            </style>
        </head>
        <body>
            <div class="email-bg">
                <div class="shell">
                    <div class="hero">
                        <div class="brand">serenity stock monitor</div>
                        <h1>{html.escape(subject)}</h1>
                        <div class="summary">
                            账号：@{html.escape(watch['username'])} · 规则：{html.escape(watch['tag'])} ·
                            间隔：{html.escape(str(watch['interval_seconds']))} 秒 ·
                            启动推送：{raw_count} 条 · 主帖入邮：{len(items)} 条
                        </div>
                    </div>
                    <div class="content">
                        {''.join(cards) if cards else '<p>本次启动批量中没有可发送的主帖。</p>'}
                    </div>
                    <div class="footer">
                        本邮件由 monitor_X_stock_god 自动生成。内容仅用于研究和跟踪，不构成投资建议。
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

    def _send_realtime_email(self, username, symbols, tweet, zh):
        symbol_text = _format_symbols_text(symbols)
        subject = f"📈 {username} 新帖 {symbol_text}"
        body = (
            f"【中文翻译】\n{zh}\n\n"
            f"【原文】\n{tweet.get('text') or ''}\n\n"
            f"时间：{tweet.get('created_at') or '-'}\n"
            f"原帖：{tweet.get('url') or ''}"
        )
        send_email(subject, body, body_html=self._single_tweet_html(subject, username, symbols, tweet, zh))

    def _single_tweet_html(self, subject, username, symbols, tweet, zh):
        symbol_html = "".join(
            f"<span class=\"tag\">{html.escape(_format_symbol_label(symbol))}</span>" for symbol in symbols
        )
        if not symbol_html:
            symbol_html = "<span class=\"tag muted\">无股票符号</span>"

        return f"""
        <!DOCTYPE html>
        <html lang="zh-CN">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    background: #0b1020;
                    color: #172033;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
                    line-height: 1.58;
                    font-size: 14px;
                }}
                .email-bg {{ width: 100%; background: #0b1020; padding: 24px 0; }}
                .shell {{
                    max-width: 820px;
                    margin: 0 auto;
                    background: #f8fafc;
                    border: 1px solid #27324a;
                    border-radius: 14px;
                    overflow: hidden;
                }}
                .hero {{
                    background: #10182c;
                    color: #ffffff;
                    padding: 30px 34px 26px;
                }}
                .brand {{
                    color: #67e8f9;
                    font-size: 12px;
                    font-weight: 700;
                    letter-spacing: 0.14em;
                    text-transform: uppercase;
                    margin-bottom: 12px;
                }}
                h1 {{ margin: 0; font-size: 26px; line-height: 1.24; color: #ffffff; }}
                .summary {{ margin-top: 14px; color: #cbd5e1; }}
                .content {{ padding: 26px 30px 32px; }}
                .ticker-row {{ margin-bottom: 16px; }}
                .tag {{
                    display: inline-block;
                    padding: 4px 9px;
                    margin: 0 6px 6px 0;
                    border-radius: 999px;
                    background: #dff7f2;
                    color: #0f766e;
                    font-weight: 800;
                    font-size: 13px;
                }}
                .tag.muted {{ background: #e2e8f0; color: #475569; }}
                .meta {{
                    color: #64748b;
                    font-size: 13px;
                    margin-bottom: 16px;
                }}
                .panel {{
                    border-radius: 10px;
                    padding: 15px 17px;
                    margin-bottom: 14px;
                }}
                .translation {{
                    background: #f0fdfa;
                    border: 1px solid #b6ece4;
                }}
                .original {{
                    color: #475569;
                    background: #ffffff;
                    border: 1px solid #d8e1ed;
                }}
                h2 {{
                    margin: 0 0 8px;
                    font-size: 15px;
                    color: #0f172a;
                    border-left: 4px solid #14b8a6;
                    padding-left: 8px;
                }}
                p {{ margin: 0; }}
                .action {{
                    display: inline-block;
                    margin-top: 6px;
                    color: #2563eb;
                    text-decoration: none;
                    font-weight: 800;
                }}
                .footer {{
                    padding: 16px 30px 24px;
                    color: #64748b;
                    font-size: 12px;
                    background: #eef2f7;
                    border-top: 1px solid #d6dee9;
                }}
            </style>
        </head>
        <body>
            <div class="email-bg">
                <div class="shell">
                    <div class="hero">
                        <div class="brand">serenity stock monitor</div>
                        <h1>{html.escape(subject)}</h1>
                        <div class="summary">
                            @{html.escape(username)} · {html.escape(tweet.get('created_at') or '-')}
                        </div>
                    </div>
                    <div class="content">
                        <div class="ticker-row">{symbol_html}</div>
                        <div class="meta">原帖：<a class="action" href="{html.escape(tweet.get('url') or '')}">打开 X 链接</a></div>
                        <section class="panel translation">
                            <h2>中文翻译</h2>
                            <p>{html.escape(zh or '').replace(chr(10), '<br>')}</p>
                        </section>
                        <section class="panel original">
                            <h2>原文</h2>
                            <p>{html.escape(tweet.get('text') or '').replace(chr(10), '<br>')}</p>
                        </section>
                    </div>
                    <div class="footer">
                        本邮件由 monitor_X_stock_god 自动生成。内容仅用于研究和跟踪，不构成投资建议。
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

    def _on_error(self, ws, error):
        print(f"WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        print(f"WebSocket closed: code={close_status_code} msg={close_msg}")

    def _shutdown(self, signum, frame):
        if self._shutting_down:
            return
        self._shutting_down = True
        print("\nStopping monitor...")
        if self.config.get("deactivate_on_exit") and self.rule_id:
            try:
                RuleManager(self.config["api_key"]).deactivate(self.rule_id)
                print(f"Rule deactivated: {self.rule_id}")
            except Exception as exc:
                print(f"⚠️ deactivate failed: {exc}")
                print(f"   请手动执行: python rules.py deactivate {self.rule_id}")
        if self.ws:
            self.ws.close()
        sys.exit(0)


def _format_symbol_label(symbol):
    name = SYMBOL_NAMES.get(symbol)
    return f"${symbol} · {name}" if name else f"${symbol}"


def _format_symbols_text(symbols):
    return ", ".join(_format_symbol_label(symbol) for symbol in symbols) if symbols else "无股票符号"


def main():
    Monitor().run()


if __name__ == "__main__":
    main()

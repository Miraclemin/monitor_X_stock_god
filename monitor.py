import importlib
import json
import signal
import sys

import websocket

import history
from config import load_config
from email_sender import send_email
from notify import notify
from rules import RuleManager
from store import get_translation, normalize_tweet, save_tweet, update_translation


translate_text = importlib.import_module("translate").translate_text


WS_URL = "wss://ws.twitterapi.io/twitter/tweet/websocket"
STARTUP_BATCH_SIZE = 20


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
            is_startup_batch = self._is_startup_batch(tweets)
            if is_startup_batch:
                self._send_startup_batch_email(tweets)
            for tweet in tweets:
                self._handle_tweet(tweet, event_type, force_email=is_startup_batch)
            return

        if event_type == "fast_tweet":
            self._handle_tweet(event.get("tweet") or {}, event_type)
            return

        print(f"Unhandled event_type={event_type}")

    def _handle_tweet(self, raw_tweet, event_type, force_email=False):
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
            if not force_email:
                return

        username = tweet.get("author_screen_name") or self.config["watch"]["username"]
        zh = get_translation(tweet_id) if force_email else None
        if not zh:
            zh = translate_text(tweet.get("text") or "")
        if zh:
            update_translation(tweet_id, zh)
            self._send_realtime_email(username, symbols, tweet, zh, startup_batch=force_email)

        if force_email and not is_new:
            return
        title = f"🔔 ${username} 新帖"
        symbol_text = ", ".join(f"${s}" for s in symbols) if symbols else "无股票符号"
        body = f"{symbol_text}\n{(tweet.get('text') or '')[:200]}"
        notify(title, body, tweet.get("url"), sound=self.config.get("notify", {}).get("sound", True))

    def _is_startup_batch(self, tweets):
        if self._startup_batch_handled or len(tweets) < STARTUP_BATCH_SIZE:
            return False
        self._startup_batch_handled = True
        return True

    def _send_startup_batch_email(self, tweets):
        watch = self.config["watch"]
        subject = f"监控已启动 @{watch['username']} 最近{len(tweets)}条"
        body = (
            f"监控账号：@{watch['username']}\n"
            f"规则标签：{watch['tag']}\n"
            f"规则 ID：{self.rule_id or '-'}\n"
            f"检查间隔：{watch['interval_seconds']} 秒\n"
            f"启动批量推送：{len(tweets)} 条\n"
            "后续会逐条翻译并发送这批启动推文。"
        )
        send_email(subject, body)

    def _send_realtime_email(self, username, symbols, tweet, zh, startup_batch=False):
        symbol_text = ", ".join(f"${s}" for s in symbols) if symbols else "无股票符号"
        label = "启动补发" if startup_batch else "新帖"
        subject = f"📈 {username} {label} {symbol_text}"
        body = (
            f"【中文翻译】\n{zh}\n\n"
            f"【原文】\n{tweet.get('text') or ''}\n\n"
            f"时间：{tweet.get('created_at') or '-'}\n"
            f"原帖：{tweet.get('url') or ''}"
        )
        send_email(subject, body)

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


def main():
    Monitor().run()


if __name__ == "__main__":
    main()

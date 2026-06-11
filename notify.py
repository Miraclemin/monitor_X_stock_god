import base64
import hashlib
import hmac
import subprocess
import time

import requests

from config import load_config


def notify(title, body, url=None, sound=True):
    config = load_config()
    settings = config.get("notify") or {}

    print(f"\n{title}\n{body}")
    if url:
        print(url)

    if settings.get("desktop"):
        _desktop(title, body, sound and settings.get("sound", True))

    telegram = settings.get("telegram") or {}
    if telegram.get("enabled"):
        _telegram(telegram, title, body, url)

    webhook = settings.get("webhook") or {}
    if webhook.get("enabled"):
        _webhook(webhook, title, body, url)

    feishu = settings.get("feishu") or {}
    if feishu.get("enabled"):
        _feishu(feishu, title, body, url)


def _desktop(title, body, sound):
    try:
        script = f'display notification "{_as_quote(body)}" with title "{_as_quote(title)}"'
        if sound:
            script += ' sound name "Glass"'
        subprocess.run(["osascript", "-e", script], check=False, timeout=10)
    except Exception as exc:
        print(f"[notify.desktop] {exc}")


def _telegram(settings, title, body, url):
    try:
        text = f"{title}\n{body}"
        if url:
            text += f"\n{url}"
        endpoint = f"https://api.telegram.org/bot{settings['bot_token']}/sendMessage"
        payload = {"chat_id": settings["chat_id"], "text": text, "disable_web_page_preview": False}
        requests.post(endpoint, json=payload, timeout=15).raise_for_status()
    except Exception as exc:
        print(f"[notify.telegram] {exc}")


def _webhook(settings, title, body, url):
    try:
        requests.post(settings["url"], json={"title": title, "body": body, "url": url}, timeout=15).raise_for_status()
    except Exception as exc:
        print(f"[notify.webhook] {exc}")


def _feishu(settings, title, body, url):
    try:
        webhook = settings.get("webhook")
        if not webhook:
            print("[notify.feishu] no webhook configured")
            return
        payload = {"msg_type": "interactive", "card": _feishu_card(title, body, url)}
        secret = settings.get("secret")
        if secret:
            timestamp = str(int(time.time()))
            digest = hmac.new(f"{timestamp}\n{secret}".encode(), digestmod=hashlib.sha256).digest()
            payload["timestamp"] = timestamp
            payload["sign"] = base64.b64encode(digest).decode()
        resp = requests.post(webhook, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code"):
            print(f"[notify.feishu] code={data['code']} msg={data.get('msg')}")
    except Exception as exc:
        print(f"[notify.feishu] {exc}")


def _feishu_card(title, body, url):
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": body or ""}}]
    if url:
        elements.append({
            "tag": "action",
            "actions": [{"tag": "button", "text": {"tag": "plain_text", "content": "查看推文"}, "type": "primary", "url": url}],
        })
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": title or ""}},
        "elements": elements,
    }


def _as_quote(value):
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')

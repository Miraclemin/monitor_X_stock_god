import subprocess

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


def _as_quote(value):
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"true", "1", "yes"}


def _str(name, default=""):
    val = os.environ.get(name)
    return val if val is not None else default


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _list(name):
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


def _usernames():
    names = _list("WATCH_USERNAMES") or _list("WATCH_USERNAME")
    return names or ["aleabitoreddit"]


def load_config():
    """Load config from .env into the nested dict shape the rest of the app expects."""
    return {
        "api_key": _str("TWITTERAPI_KEY"),
        "watch": {
            "usernames": _usernames(),
            "tag": _str("WATCH_TAG", "serenity_stock_god"),
            "interval_seconds": _float("WATCH_INTERVAL_SECONDS", 60),
        },
        "rule_id": _str("RULE_ID"),
        "db_path": _str("DB_PATH", "data/monitor.sqlite"),
        "deactivate_on_exit": _bool("DEACTIVATE_ON_EXIT", True),
        "history": {
            "enabled": _bool("HISTORY_ENABLED", True),
            "run_on_start": _bool("HISTORY_RUN_ON_START", True),
            "mode_on_start": _str("HISTORY_MODE_ON_START", "incremental"),
            "x_curl_dir": _str("HISTORY_X_CURL_DIR", "../x_curl"),
            "max_pages": _int("HISTORY_MAX_PAGES", 200),
            "pause_seconds": _float("HISTORY_PAUSE_SECONDS", 0.8),
            "max_months": _int("HISTORY_MAX_MONTHS", 0),
        },
        "llm": {
            "url": _str("LLM_URL"),
            "key": _str("LLM_KEY"),
            "model": _str("LLM_MODEL"),
        },
        "translate": {"enabled": _bool("TRANSLATE_ENABLED", True)},
        "email": {
            "enabled": _bool("EMAIL_ENABLED", False),
            "smtp_host": _str("EMAIL_SMTP_HOST"),
            "smtp_port": _int("EMAIL_SMTP_PORT", 587),
            "use_tls": _bool("EMAIL_USE_TLS", True),
            "user": _str("EMAIL_USER"),
            "password": _str("EMAIL_PASSWORD"),
            "from": _str("EMAIL_FROM"),
            "to": _list("EMAIL_TO"),
        },
        "notify": {
            "desktop": _bool("NOTIFY_DESKTOP", True),
            "sound": _bool("NOTIFY_SOUND", True),
            "telegram": {
                "enabled": _bool("NOTIFY_TELEGRAM_ENABLED", False),
                "bot_token": _str("NOTIFY_TELEGRAM_BOT_TOKEN"),
                "chat_id": _str("NOTIFY_TELEGRAM_CHAT_ID"),
            },
            "webhook": {
                "enabled": _bool("NOTIFY_WEBHOOK_ENABLED", False),
                "url": _str("NOTIFY_WEBHOOK_URL"),
            },
        },
    }

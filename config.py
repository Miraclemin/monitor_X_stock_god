import json
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = json.load(f)

    api_key = os.environ.get("TWITTERAPI_KEY")
    if api_key:
        config["api_key"] = api_key

    return config

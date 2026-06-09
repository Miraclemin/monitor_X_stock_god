import html
import json
import shlex
import subprocess
import urllib.parse
from pathlib import Path

from extract import extract_symbols, parse_x_date


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
TARGET_USER_ID = "1940360837547565056"
X_CURL_DIR = PROJECT_ROOT / "x_curl"
CURL_FILES = {
    "posts": "UserTweets.curl",
    "replies": "UserTweetsAndReplies.curl",
    "premium": "UserSuperFollowTweets.curl",
}


def parse_curl(path: Path):
    text = path.read_text()
    args = [arg for arg in shlex.split(text, posix=True) if arg.strip()]
    if not args or args[0] != "curl":
        raise ValueError(f"{path} is not a curl command")
    return args


def set_cursor(url: str, cursor: str | None) -> str:
    parts = urllib.parse.urlsplit(url)
    qs = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    variables = json.loads(qs.get("variables", ["{}"])[0])
    if cursor:
        variables["cursor"] = cursor
    else:
        variables.pop("cursor", None)
    qs["variables"] = [json.dumps(variables, separators=(",", ":"))]
    query = urllib.parse.urlencode(qs, doseq=True)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def curl_fetch(curl_file: Path, cursor: str | None):
    args = parse_curl(curl_file)
    args[1] = set_cursor(args[1], cursor)
    args.extend(["-sS", "--compressed"])
    out = subprocess.check_output(args, cwd=PROJECT_ROOT)
    body = out.decode("utf-8", "replace")
    data = json.loads(body)
    if "errors" in data and not data.get("data"):
        raise RuntimeError(json.dumps(data["errors"], ensure_ascii=False)[:1000])
    return body, data


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for val in obj.values():
            yield from walk(val)
    elif isinstance(obj, list):
        for val in obj:
            yield from walk(val)


def find_bottom_cursor(data):
    for node in walk(data):
        if node.get("cursorType") == "Bottom" and node.get("value"):
            return node["value"]
    return None


def normalize_tweet(node):
    if node.get("__typename") != "Tweet" or "legacy" not in node:
        return None
    legacy = node.get("legacy", {})
    core_user = (((node.get("core") or {}).get("user_results") or {}).get("result") or {})
    author_id = core_user.get("rest_id") or legacy.get("user_id_str")
    if author_id != TARGET_USER_ID:
        return None
    tweet_id = legacy.get("id_str") or node.get("rest_id")
    if not tweet_id:
        return None
    note = (((node.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {})
    text = note.get("text") or legacy.get("full_text") or ""
    text = html.unescape(text)
    created_at = parse_x_date(legacy.get("created_at"))
    screen = (((core_user.get("core") or {}).get("screen_name")) or "aleabitoreddit")
    return {
        "tweet_id": tweet_id,
        "author_id": author_id,
        "author_screen_name": screen,
        "created_at": created_at,
        "text": text,
        "url": f"https://x.com/{screen}/status/{tweet_id}",
        "favorite_count": legacy.get("favorite_count") or 0,
        "reply_count": legacy.get("reply_count") or 0,
        "retweet_count": legacy.get("retweet_count") or 0,
        "quote_count": legacy.get("quote_count") or 0,
        "symbols": extract_symbols(text, legacy, note),
        "raw_json": json.dumps(node, ensure_ascii=False, separators=(",", ":")),
    }

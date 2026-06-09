import argparse
import time
from pathlib import Path

from config import load_config
from notify import notify
from store import save_ingest_tweet
from xfetch import CURL_FILES, X_CURL_DIR, curl_fetch, find_bottom_cursor, normalize_tweet, walk


BASE_DIR = Path(__file__).resolve().parent


def run_history(mode, x_curl_dir=None, max_pages=200, pause=0.8):
    curl_dir = _resolve_curl_dir(x_curl_dir)
    totals = {"fetched": 0, "new": 0, "by_source": {}}
    latest = None

    for source, filename in CURL_FILES.items():
        try:
            summary, source_latest = _run_source(source, curl_dir / filename, mode, max_pages, pause)
        except Exception as exc:
            print(f"history warning: source={source} skipped: {exc}")
            summary, source_latest = {"fetched": 0, "new": 0}, None

        totals["by_source"][source] = summary
        totals["fetched"] += summary["fetched"]
        totals["new"] += summary["new"]
        latest = _max_latest(latest, source_latest)

    if totals["new"] > 0:
        body = f"{_format_distribution(totals['by_source'])}；最新 {latest.get('created_at') if latest else '-'}"
        notify(f"📥 历史回补 {totals['new']} 条", body, url=latest.get("url") if latest else None, sound=True)

    return totals


def _run_source(source, curl_path, mode, max_pages, pause):
    cursor = None
    seen_cursor = set()
    summary = {"fetched": 0, "new": 0}
    latest = None

    for page in range(max_pages):
        body, data = curl_fetch(curl_path, cursor)
        tweets = _page_tweets(data)
        page_new = 0
        summary["fetched"] += len(tweets)

        for tweet in tweets:
            is_new, symbols = save_ingest_tweet(tweet, source)
            if not is_new:
                continue
            page_new += 1
            summary["new"] += 1
            latest = _max_latest(latest, tweet)
            print(f"[history:{source}] {tweet.get('created_at')} {tweet.get('tweet_id')} {symbols} {(tweet.get('text') or '')[:60]}")

        next_cursor = find_bottom_cursor(data)
        if not next_cursor or next_cursor == cursor or len(tweets) == 0:
            break
        if next_cursor in seen_cursor:
            break
        if mode == "incremental" and page_new == 0:
            break

        seen_cursor.add(next_cursor)
        cursor = next_cursor
        time.sleep(pause)

    return summary, latest


def _page_tweets(data):
    tweets = {}
    for node in walk(data):
        tweet = normalize_tweet(node)
        if tweet:
            tweets[tweet["tweet_id"]] = tweet
    return list(tweets.values())


def _resolve_curl_dir(x_curl_dir):
    if not x_curl_dir:
        return Path(X_CURL_DIR)
    path = Path(x_curl_dir)
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


def _max_latest(current, candidate):
    if not candidate:
        return current
    if not current:
        return candidate
    if (candidate.get("created_at") or "") > (current.get("created_at") or ""):
        return candidate
    return current


def _format_distribution(by_source):
    parts = []
    for source in CURL_FILES:
        summary = by_source.get(source) or {}
        parts.append(f"{source} {summary.get('new', 0)}")
    return " / ".join(parts)


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true")
    group.add_argument("--incremental", action="store_true")
    args = parser.parse_args()

    config = load_config()
    settings = config.get("history") or {}
    mode = "all" if args.all else "incremental"
    result = run_history(
        mode,
        x_curl_dir=settings.get("x_curl_dir"),
        max_pages=int(settings.get("max_pages", 200)),
        pause=float(settings.get("pause_seconds", 0.8)),
    )
    print(result)


if __name__ == "__main__":
    main()

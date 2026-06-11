import argparse
import datetime as dt
import time
from pathlib import Path

from config import load_config
from notify import notify
from store import save_ingest_tweet
from xfetch import CURL_FILES, X_CURL_DIR, curl_fetch, curl_user_id, find_bottom_cursor, normalize_tweet, walk


BASE_DIR = Path(__file__).resolve().parent


def run_history(mode, x_curl_dir=None, max_pages=200, pause=0.8, usernames=None, max_months=0):
    curl_base = _resolve_curl_dir(x_curl_dir)
    if usernames is None:
        usernames = load_config()["watch"]["usernames"]
    cutoff = _cutoff_iso(max_months)
    if cutoff:
        print(f"history: 只回补 {cutoff} 之后的帖子（最近 {max_months} 个月）")
    totals = {"fetched": 0, "new": 0, "by_user": {}}
    latest = None

    for username in usernames:
        user_dir = curl_base / username
        if not user_dir.is_dir():
            print(f"history: @{username} 没有 curl 目录（{user_dir}），跳过历史下载")
            continue

        user_summary = {"fetched": 0, "new": 0, "by_source": {}}
        for source, filename in CURL_FILES.items():
            curl_path = user_dir / filename
            if not curl_path.exists():
                print(f"history: @{username} 缺少 {filename}，跳过 {source}")
                continue
            try:
                summary, source_latest = _run_source(source, curl_path, mode, max_pages, pause, username, cutoff)
            except Exception as exc:
                print(f"history warning: user={username} source={source} skipped: {exc}")
                summary, source_latest = {"fetched": 0, "new": 0}, None

            user_summary["by_source"][source] = summary
            user_summary["fetched"] += summary["fetched"]
            user_summary["new"] += summary["new"]
            latest = _max_latest(latest, source_latest)

        totals["by_user"][username] = user_summary
        totals["fetched"] += user_summary["fetched"]
        totals["new"] += user_summary["new"]

    if totals["new"] > 0:
        body = f"{_format_distribution(totals['by_user'])}；最新 {latest.get('created_at') if latest else '-'}"
        notify(f"📥 历史回补 {totals['new']} 条", body, url=latest.get("url") if latest else None, sound=True)

    return totals


def _run_source(source, curl_path, mode, max_pages, pause, username, cutoff=None):
    target_user_id = curl_user_id(curl_path)
    if not target_user_id:
        raise ValueError(f"{curl_path} 的 URL variables 中没有 userId")
    cursor = None
    seen_cursor = set()
    summary = {"fetched": 0, "new": 0}
    latest = None

    for page in range(max_pages):
        body, data = curl_fetch(curl_path, cursor)
        tweets = _page_tweets(data, target_user_id, username)
        in_range = [t for t in tweets if not cutoff or (t.get("created_at") or "") >= cutoff]
        page_new = 0
        summary["fetched"] += len(tweets)

        for tweet in in_range:
            is_new, symbols = save_ingest_tweet(tweet, source)
            if not is_new:
                continue
            page_new += 1
            summary["new"] += 1
            latest = _max_latest(latest, tweet)
            print(f"[history:{username}:{source}] {tweet.get('created_at')} {tweet.get('tweet_id')} {symbols} {(tweet.get('text') or '')[:60]}")

        # 整页都早于截止时间：时间线已翻过界，停止（置顶老帖不会单独触发）
        if cutoff and tweets and not in_range:
            break

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


def _page_tweets(data, target_user_id, fallback_screen_name):
    tweets = {}
    for node in walk(data):
        tweet = normalize_tweet(node, target_user_id, fallback_screen_name)
        if tweet:
            tweets[tweet["tweet_id"]] = tweet
    return list(tweets.values())


def _cutoff_iso(max_months):
    if not max_months or max_months <= 0:
        return None
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * max_months)
    return cutoff.isoformat().replace("+00:00", "Z")


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


def _format_distribution(by_user):
    return " / ".join(f"@{username} {summary.get('new', 0)}" for username, summary in by_user.items())


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true")
    group.add_argument("--incremental", action="store_true")
    parser.add_argument("--months", type=int, default=None, help="只回补最近 N 个月，覆盖 HISTORY_MAX_MONTHS；0 表示不限制")
    args = parser.parse_args()

    config = load_config()
    settings = config.get("history") or {}
    mode = "all" if args.all else "incremental"
    max_months = args.months if args.months is not None else int(settings.get("max_months", 0))
    result = run_history(
        mode,
        x_curl_dir=settings.get("x_curl_dir"),
        max_pages=int(settings.get("max_pages", 200)),
        pause=float(settings.get("pause_seconds", 0.8)),
        max_months=max_months,
    )
    print(result)


if __name__ == "__main__":
    main()

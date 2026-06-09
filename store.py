import datetime as dt
import json
import sqlite3
from pathlib import Path

from config import load_config
from extract import extract_symbols, parse_x_date


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "monitor.sqlite"


def connect():
    config = load_config()
    db_path = Path(config.get("db_path") or DEFAULT_DB_PATH)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        pragma journal_mode = wal;
        create table if not exists tweets (
            tweet_id text primary key,
            source text not null,
            author_id text,
            author_screen_name text,
            created_at text,
            text text not null,
            url text,
            favorite_count integer,
            reply_count integer,
            retweet_count integer,
            quote_count integer,
            raw_json text not null,
            text_zh text
        );
        create table if not exists mentions (
            id integer primary key autoincrement,
            symbol text not null,
            tweet_id text not null references tweets(tweet_id) on delete cascade,
            mentioned_at text not null,
            text text not null,
            source text not null,
            unique(symbol, tweet_id)
        );
        create index if not exists idx_mentions_symbol_time on mentions(symbol, mentioned_at);
        """
    )
    _ensure_text_zh(con)
    con.commit()
    return con


def normalize_tweet(raw, event_type):
    raw = raw or {}
    tweet_id = str(raw.get("id") or "")
    author = raw.get("author") or {}
    screen_name = author.get("userName") or raw.get("screen_name") or ""
    created_at = _created_at(raw)
    url = raw.get("url") or (f"https://x.com/{screen_name}/status/{tweet_id}" if screen_name and tweet_id else "")

    return {
        "tweet_id": tweet_id,
        "event_type": event_type,
        "author_id": str(author.get("id") or ""),
        "author_screen_name": screen_name,
        "created_at": created_at,
        "text": raw.get("text") or "",
        "url": url,
        "favorite_count": int(raw.get("likeCount") or 0),
        "reply_count": int(raw.get("replyCount") or 0),
        "retweet_count": int(raw.get("retweetCount") or 0),
        "quote_count": int(raw.get("quoteCount") or 0),
        "entities": raw.get("entities") or {},
        "snow_delay_ms": raw.get("snow_delay_ms"),
        "raw_json": json.dumps(raw, ensure_ascii=False, separators=(",", ":")),
    }


def save_tweet(tweet_norm):
    symbols = _extract_symbols(tweet_norm)
    mentioned_at = tweet_norm.get("created_at") or _utc_now()
    return _save_row(tweet_norm, symbols, mentioned_at, "realtime_ws")


def save_ingest_tweet(tweet_dict, source):
    symbols = tweet_dict.get("symbols") or []
    mentioned_at = tweet_dict.get("created_at") or _utc_now()
    row = {
        "tweet_id": tweet_dict["tweet_id"],
        "author_id": tweet_dict.get("author_id"),
        "author_screen_name": tweet_dict.get("author_screen_name"),
        "created_at": tweet_dict.get("created_at"),
        "text": tweet_dict.get("text") or "",
        "url": tweet_dict.get("url"),
        "favorite_count": tweet_dict.get("favorite_count", 0),
        "reply_count": tweet_dict.get("reply_count", 0),
        "retweet_count": tweet_dict.get("retweet_count", 0),
        "quote_count": tweet_dict.get("quote_count", 0),
        "raw_json": tweet_dict.get("raw_json") or "{}",
    }
    return _save_row(row, symbols, mentioned_at, source)


def update_translation(tweet_id, text_zh):
    with connect() as con:
        con.execute("update tweets set text_zh=? where tweet_id=?", (text_zh, tweet_id))


def _save_row(row, symbols, mentioned_at, source):
    with connect() as con:
        cur = con.execute(
            """
            insert or ignore into tweets(
                tweet_id, source, author_id, author_screen_name, created_at, text, url,
                favorite_count, reply_count, retweet_count, quote_count, raw_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["tweet_id"],
                source,
                row.get("author_id"),
                row.get("author_screen_name"),
                row.get("created_at"),
                row.get("text") or "",
                row.get("url"),
                row.get("favorite_count", 0),
                row.get("reply_count", 0),
                row.get("retweet_count", 0),
                row.get("quote_count", 0),
                row.get("raw_json") or "{}",
            ),
        )
        is_new = cur.rowcount > 0

        for symbol in symbols:
            con.execute(
                """
                insert or ignore into mentions(symbol, tweet_id, mentioned_at, text, source)
                values (?, ?, ?, ?, ?)
                """,
                (symbol, row["tweet_id"], mentioned_at, row.get("text") or "", source),
            )

    return is_new, symbols


def _ensure_text_zh(con):
    cols = {row[1] for row in con.execute("pragma table_info(tweets)")}
    if "text_zh" not in cols:
        con.execute("alter table tweets add column text_zh text")


def _extract_symbols(tweet_norm):
    legacy = {"entities": tweet_norm.get("entities") or {}}
    return extract_symbols(tweet_norm.get("text") or "", legacy, {})


def _created_at(raw):
    if raw.get("createdAt"):
        return parse_x_date(raw["createdAt"])

    created_ms = raw.get("created_ms")
    if created_ms is None:
        return None
    created = dt.datetime.fromtimestamp(int(created_ms) / 1000, tz=dt.timezone.utc)
    return created.isoformat().replace("+00:00", "Z")


def _utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

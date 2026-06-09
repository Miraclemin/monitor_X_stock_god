import argparse
import json
import re
import time
import urllib.error
import urllib.request

from config import load_config
from store import connect, update_translation


def _llm_config():
    return load_config().get("llm") or {}


def chat(prompt, retries=8, timeout=180):
    settings = _llm_config()
    url = settings.get("url")
    key = settings.get("key")
    model = settings.get("model")
    if not url or not key or not model:
        raise RuntimeError("llm config missing url/key/model")

    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}).encode()
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 529) and i < retries - 1:
                wait = 4 * (i + 1)
                print(f"  http {exc.code}, wait {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if i < retries - 1:
                time.sleep(4 * (i + 1))
                continue
            raise
    raise RuntimeError("chat failed")


def translate_text(text):
    settings = load_config().get("translate") or {}
    if not settings.get("enabled", True) or not (text or "").strip():
        return None

    prompt = (
        "你是金融/半导体领域的中英翻译。把下面这条英文推文翻成自然流畅的简体中文。"
        "保留 $股票代码、数字、公司/产品专名不译，术语用业内译法（CPO=共封装光学、InP=磷化铟、HBM 保留等）。"
        "只输出译文，不要解释，不要代码块。\n\n"
        f"{text}"
    )
    try:
        return chat(prompt).strip()
    except Exception as exc:
        print(f"translate warning: {exc}")
        return None


def parse_marked(text):
    result = {}
    parts = re.split(r"@@@(.+?)@@@", text)
    it = iter(parts[1:])
    for mid, body in zip(it, it):
        result[mid.strip()] = body.strip()
    return result


def translate_tweets(batch=12, pause=1.0, limit=None):
    with connect() as con:
        rows = con.execute(
            "select tweet_id, text from tweets where text_zh is null and trim(text) <> '' order by created_at desc"
        ).fetchall()
        if limit:
            rows = rows[:limit]

    print(f"tweets to translate: {len(rows)}")
    done = 0
    nbatch = (len(rows) + batch - 1) // batch
    for i in range(0, len(rows), batch):
        chunk = rows[i:i + batch]
        head = (
            "你是金融/半导体领域的中英翻译。把下面每一条英文推文翻成自然流畅的简体中文。"
            "保留 $股票代码、数字、公司/产品专名不译，术语用业内译法（CPO=共封装光学、InP=磷化铟、HBM 保留等）。\n"
            "输出格式：对每条，先单独一行写 @@@该条的id@@@，下一行起写中文译文（可多行），再写下一条。"
            "除此之外不要输出任何多余文字或代码块标记。\n\n"
        )
        body = "".join(f"@@@{r['tweet_id']}@@@\n{r['text']}\n\n" for r in chunk)
        try:
            out = parse_marked(chat(head + body))
        except Exception as exc:
            print(f"  batch {i // batch + 1} failed: {exc}", flush=True)
            time.sleep(pause)
            continue

        for row in chunk:
            zh = out.get(str(row["tweet_id"]))
            if zh:
                update_translation(row["tweet_id"], zh)
                done += 1
        print(f"  batch {i // batch + 1}/{nbatch} -> {done} translated", flush=True)
        time.sleep(pause)
    print(f"translated {done} tweets", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Translate stored tweets to Chinese.")
    parser.add_argument("--batch", type=int, default=12)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--pause", type=float, default=1.0)
    args = parser.parse_args()
    translate_tweets(batch=args.batch, pause=args.pause, limit=args.limit)


if __name__ == "__main__":
    main()

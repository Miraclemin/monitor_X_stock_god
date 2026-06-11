"""给新监控账号克隆 curl 文件：自动查 userId，从现有账号的 curl 替换生成。

用法：
    python add_user_curl.py <用户名>             # 模板取第一个已有 curl 的监控账号
    python add_user_curl.py <用户名> --from xxx  # 指定模板账号
"""
import argparse
import sys
from pathlib import Path

import requests

from config import load_config
from history import _resolve_curl_dir
from xfetch import CURL_FILES, curl_user_id


def resolve_user_id(api_key, username):
    resp = requests.get(
        "https://api.twitterapi.io/twitter/user/info",
        params={"userName": username},
        headers={"X-API-Key": api_key},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    user = data.get("data") or {}
    user_id = str(user.get("id") or "")
    if data.get("status") != "success" or not user_id:
        raise RuntimeError(f"查不到 @{username} 的 userId：{data}")
    return user_id, user


def check_search_visibility(api_key, username):
    """tweet_filter 基于 X 搜索层；from: 搜不到的账号实时监控不会触发。"""
    try:
        resp = requests.get(
            "https://api.twitterapi.io/twitter/tweet/advanced_search",
            params={"query": f"from:{username}", "queryType": "Latest"},
            headers={"X-API-Key": api_key},
            timeout=20,
        )
        resp.raise_for_status()
        return len(resp.json().get("tweets") or [])
    except Exception as exc:
        print(f"搜索可见性检查失败（不影响克隆）：{exc}")
        return None


def find_source_dir(curl_base, usernames, explicit):
    candidates = [explicit] if explicit else usernames
    for name in candidates:
        if not name:
            continue
        user_dir = curl_base / name
        if any((user_dir / filename).exists() for filename in CURL_FILES.values()):
            return user_dir
    raise RuntimeError(f"在 {curl_base} 下找不到可作模板的 curl 目录，请先按 README 配置一个账号的 curl")


def main():
    parser = argparse.ArgumentParser(description="从现有账号克隆 curl 文件给新账号（自动替换 userId）")
    parser.add_argument("username", help="新账号用户名，不带 @")
    parser.add_argument("--from", dest="source", default=None, help="模板账号目录名")
    args = parser.parse_args()
    username = args.username.lstrip("@")

    config = load_config()
    curl_base = _resolve_curl_dir(config["history"]["x_curl_dir"])
    target_dir = curl_base / username
    if target_dir.is_dir() and any(target_dir.iterdir()):
        print(f"目标目录已存在且非空：{target_dir}，如需重建请先删除")
        sys.exit(1)

    source_dir = find_source_dir(curl_base, config["watch"]["usernames"], args.source)
    new_id, user = resolve_user_id(config["api_key"], username)
    print(f"@{user.get('userName')}（{user.get('name')}）userId={new_id} 粉丝={user.get('followers')}")

    visible = check_search_visibility(config["api_key"], username)
    if visible == 0:
        print(
            "⚠️ 警告：X 搜索查不到该账号的任何帖子（from: 搜索返回 0 条）。\n"
            "   tweet_filter 规则基于搜索层，该账号的实时监控可能永远不会触发，详见 README 注意事项。"
        )
    elif visible:
        print(f"搜索可见性 OK：from:{username} 可搜到 {visible} 条")

    target_dir.mkdir(parents=True, exist_ok=True)
    cloned = 0
    for filename in CURL_FILES.values():
        source_path = source_dir / filename
        if not source_path.exists():
            continue
        old_id = curl_user_id(source_path)
        if not old_id:
            print(f"跳过 {filename}：解析不到模板 userId")
            continue
        target_path = target_dir / filename
        target_path.write_text(source_path.read_text().replace(old_id, new_id))
        if curl_user_id(target_path) != new_id:
            raise RuntimeError(f"{target_path} userId 替换失败")
        cloned += 1
        print(f"已生成 {target_path}")

    if cloned == 0:
        raise RuntimeError(f"模板目录 {source_dir} 中没有可用的 curl 文件")
    print(
        f"\n完成（模板：{source_dir.name}，{cloned} 个文件）。下一步：\n"
        f"1. 把 {username} 加入 .env 的 WATCH_USERNAMES\n"
        f"2. 重启 monitor.py（历史按 HISTORY_MAX_MONTHS 回补）\n"
        f"注意：curl 用的是你浏览器的登录 cookie，cookie 过期后需要重新从 DevTools 复制模板。"
    )


if __name__ == "__main__":
    main()

import argparse
import time

import requests

from config import load_config


REST_BASE = "https://api.twitterapi.io"


class RuleManager:
    def __init__(self, api_key):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": api_key})

    def list_rules(self):
        resp = self.session.get(f"{REST_BASE}/oapi/tweet_filter/get_rules", timeout=20)
        resp.raise_for_status()
        return resp.json().get("rules") or []

    def add_rule(self, tag, value, interval):
        payload = {"tag": tag, "value": value, "interval_seconds": interval}
        resp = self.session.post(f"{REST_BASE}/oapi/tweet_filter/add_rule", json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success" or not data.get("rule_id"):
            raise RuntimeError(f"add_rule failed: {data}")
        return data["rule_id"]

    def update_rule(self, rule_id, tag, value, interval, is_effect):
        payload = {
            "rule_id": rule_id,
            "tag": tag,
            "value": value,
            "interval_seconds": interval,
            "is_effect": is_effect,
        }
        resp = self.session.post(f"{REST_BASE}/oapi/tweet_filter/update_rule", json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            raise RuntimeError(f"update_rule failed: {data}")
        return data

    def ensure_active(self, tag, value, interval):
        for rule in self.list_rules():
            if rule.get("tag") == tag:
                rule_id = rule["rule_id"]
                self.update_rule(rule_id, tag, value, interval, 1)
                return rule_id

        rule_id = self.add_rule(tag, value, interval)
        self.update_rule(rule_id, tag, value, interval, 1)
        return rule_id

    def deactivate(self, rule_id, retries=3):
        last_exc = None
        for attempt in range(retries):
            try:
                rule = self._find_rule(rule_id)
                if not rule.get("is_effect"):
                    return {"status": "success", "msg": "already inactive"}
                return self.update_rule(
                    rule_id,
                    rule.get("tag"),
                    rule.get("value"),
                    rule.get("interval_seconds"),
                    0,
                )
            except Exception as exc:
                last_exc = exc
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
        raise last_exc

    def delete(self, rule_id):
        try:
            resp = self.session.post(
                f"{REST_BASE}/oapi/tweet_filter/delete_rule",
                json={"rule_id": rule_id},
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _find_rule(self, rule_id):
        for rule in self.list_rules():
            if rule.get("rule_id") == rule_id:
                return rule
        raise RuntimeError(f"rule not found: {rule_id}")


def _print_rules(rules):
    if not rules:
        print("No rules.")
        return
    for rule in rules:
        print(
            f"{rule.get('rule_id')} tag={rule.get('tag')} "
            f"value={rule.get('value')} is_effect={rule.get('is_effect')} "
            f"interval={rule.get('interval_seconds')} last_tweet_id={rule.get('last_tweet_id')}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["list", "ensure", "deactivate", "delete"])
    parser.add_argument("rule_id", nargs="?")
    args = parser.parse_args()

    config = load_config()
    watch = config["watch"]
    manager = RuleManager(config["api_key"])

    if args.command == "list":
        _print_rules(manager.list_rules())
        return

    rule_id = args.rule_id or config.get("rule_id")
    if args.command == "ensure":
        value = f"from:{watch['username']}"
        print(manager.ensure_active(watch["tag"], value, watch["interval_seconds"]))
    elif args.command == "deactivate":
        print(manager.deactivate(rule_id))
    elif args.command == "delete":
        print(manager.delete(rule_id))


if __name__ == "__main__":
    main()

import base64
import hashlib
import hmac

import pytest

import notify


WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/fake-token"


class FakeResponse:
    def __init__(self, data=None):
        self._data = data if data is not None else {"code": 0, "msg": "success"}

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


@pytest.fixture
def posted(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    return calls


def test_sends_card_to_webhook(posted):
    notify._feishu({"webhook": WEBHOOK}, "标题", "正文", "https://x.com/u/status/1")

    assert len(posted) == 1
    call = posted[0]
    assert call["url"] == WEBHOOK
    payload = call["json"]
    assert payload["msg_type"] == "interactive"
    card = payload["card"]
    assert card["header"]["title"]["content"] == "标题"
    assert card["elements"][0]["text"]["content"] == "正文"
    buttons = card["elements"][1]["actions"]
    assert buttons[0]["url"] == "https://x.com/u/status/1"


def test_signature_added_when_secret_present(posted):
    notify._feishu({"webhook": WEBHOOK, "secret": "s3cret"}, "t", "b", None)

    payload = posted[0]["json"]
    assert payload["timestamp"].isdigit()
    expected = base64.b64encode(
        hmac.new(f"{payload['timestamp']}\ns3cret".encode(), digestmod=hashlib.sha256).digest()
    ).decode()
    assert payload["sign"] == expected


def test_no_signature_without_secret(posted):
    notify._feishu({"webhook": WEBHOOK}, "t", "b", None)

    payload = posted[0]["json"]
    assert "sign" not in payload
    assert "timestamp" not in payload


def test_no_button_without_url(posted):
    notify._feishu({"webhook": WEBHOOK}, "t", "b", None)

    elements = posted[0]["json"]["card"]["elements"]
    assert all(el["tag"] != "action" for el in elements)


def test_empty_title_and_body_do_not_crash(posted):
    notify._feishu({"webhook": WEBHOOK}, None, None, None)

    card = posted[0]["json"]["card"]
    assert card["header"]["title"]["content"] == ""
    assert card["elements"][0]["text"]["content"] == ""


def test_missing_webhook_skips_post(posted, capsys):
    notify._feishu({"secret": "x"}, "t", "b", None)

    assert posted == []
    assert "no webhook configured" in capsys.readouterr().out


def test_api_business_error_is_logged_not_raised(monkeypatch, capsys):
    monkeypatch.setattr(
        notify.requests, "post",
        lambda *a, **k: FakeResponse({"code": 19021, "msg": "sign match fail"}),
    )

    notify._feishu({"webhook": WEBHOOK}, "t", "b", None)

    out = capsys.readouterr().out
    assert "19021" in out and "sign match fail" in out


def test_network_error_is_swallowed(monkeypatch, capsys):
    def boom(*a, **k):
        raise notify.requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(notify.requests, "post", boom)

    notify._feishu({"webhook": WEBHOOK}, "t", "b", None)

    assert "[notify.feishu]" in capsys.readouterr().out


def _config(feishu):
    return {
        "notify": {
            "desktop": False,
            "sound": False,
            "telegram": {"enabled": False},
            "webhook": {"enabled": False},
            "feishu": feishu,
        }
    }


def test_notify_routes_to_feishu_when_enabled(monkeypatch, posted):
    monkeypatch.setattr(notify, "load_config", lambda: _config(
        {"enabled": True, "webhook": WEBHOOK, "secret": ""}
    ))

    notify.notify("t", "b", "https://x.com/u/status/2")

    assert len(posted) == 1
    assert posted[0]["url"] == WEBHOOK


def test_notify_skips_feishu_when_disabled(monkeypatch, posted):
    monkeypatch.setattr(notify, "load_config", lambda: _config(
        {"enabled": False, "webhook": WEBHOOK, "secret": ""}
    ))

    notify.notify("t", "b", None)

    assert posted == []

import json

import httpx
import pytest
import respx

from notifier import NotifyError, TelegramNotifier

URL = "https://api.telegram.org/botTOKEN/sendMessage"


@respx.mock
def test_send_posts_expected_payload():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    TelegramNotifier("TOKEN", "42").send("hello")
    body = json.loads(route.calls.last.request.content)
    assert body["chat_id"] == "42"
    assert body["text"] == "hello"
    assert body["parse_mode"] == "HTML"


@respx.mock
def test_send_raises_on_api_error():
    respx.post(URL).mock(return_value=httpx.Response(400, json={"ok": False, "description": "chat not found"}))
    with pytest.raises(NotifyError, match="400"):
        TelegramNotifier("TOKEN", "42").send("hello")


@respx.mock
def test_network_error_does_not_leak_token():
    respx.post(URL).mock(side_effect=httpx.ConnectError("boom https://api.telegram.org/botTOKEN"))
    with pytest.raises(NotifyError) as exc:
        TelegramNotifier("TOKEN", "42").send("hello")
    assert "TOKEN" not in str(exc.value)


@respx.mock
def test_send_with_buttons():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    TelegramNotifier("TOKEN", "42").send("hi", buttons=[("앱", "https://a"), ("웹", "https://b")])
    body = json.loads(route.calls.last.request.content)
    assert body["reply_markup"] == {"inline_keyboard": [[{"text": "앱", "url": "https://a"}, {"text": "웹", "url": "https://b"}]]}

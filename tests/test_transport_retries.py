import requests
import pytest

from fusionsolar_readonly_exporter.readonly_transport import ReadOnlyTransport


class FakeResponse:
    def __init__(self, status=200, headers=None, payload=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload if payload is not None else {"ok": True}
        self.content = b"{}"
        self.text = "{}"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"status {self.status_code}")
            error.response = self
            raise error


def test_connection_reset_retries_bounded_read_request():
    sleeps = []
    transport = ReadOnlyTransport(
        delay_seconds=0,
        max_retries=2,
        backoff_base=1,
        sleep=sleeps.append,
        jitter=lambda _a, b: b,
    )
    sequence = [requests.ConnectionError("reset"), FakeResponse()]
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs)
        item = sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    transport.session.request = request
    response = transport.request(
        "GET",
        "https://region01eu5.fusionsolar.huawei.com/rest/dpcloud/auth/v1/keep-alive",
        "session.keepalive",
        capture=False,
    )
    assert response.status_code == 200
    assert len(calls) == 2
    assert sleeps == [1]
    assert calls[0]["timeout"] == (5.0, 30.0)


def test_429_respects_retry_after_hint():
    sleeps = []
    transport = ReadOnlyTransport(delay_seconds=0, max_retries=1, sleep=sleeps.append)
    sequence = [FakeResponse(429, {"Retry-After": "2"}), FakeResponse()]
    transport.session.request = lambda *args, **kwargs: sequence.pop(0)
    response = transport.request(
        "GET",
        "https://region01eu5.fusionsolar.huawei.com/rest/dpcloud/auth/v1/keep-alive",
        "session.keepalive",
        capture=False,
    )
    assert response.status_code == 200
    assert sleeps == [2.0]


def test_selected_5xx_stops_after_max_retry_count():
    transport = ReadOnlyTransport(
        delay_seconds=0,
        max_retries=2,
        sleep=lambda _seconds: None,
        jitter=lambda _a, _b: 0,
    )
    calls = []

    def request(*args, **kwargs):
        calls.append(1)
        return FakeResponse(503)

    transport.session.request = request
    with pytest.raises(requests.HTTPError):
        transport.request(
            "GET",
            "https://region01eu5.fusionsolar.huawei.com/rest/dpcloud/auth/v1/keep-alive",
            "session.keepalive",
            capture=False,
        )
    assert len(calls) == 3


def test_login_post_is_not_automatically_retried():
    transport = ReadOnlyTransport(delay_seconds=0, max_retries=3, sleep=lambda _seconds: None)
    calls = []

    def request(*args, **kwargs):
        calls.append(1)
        return FakeResponse(503)

    transport.session.request = request
    with pytest.raises(requests.HTTPError):
        transport.request(
            "POST",
            "https://eu5.fusionsolar.huawei.com/unisso/v3/validateUser.action",
            "auth.login-v3",
            params={"timeStamp": "1", "nonce": "n"},
            json_body={"organizationName": "", "username": "u", "password": "p"},
            capture=False,
        )
    assert len(calls) == 1

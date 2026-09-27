from pathlib import Path

import pytest

from fusionsolar_readonly_exporter.auth import AuthenticatedSession, _login_host_for
from fusionsolar_readonly_exporter.errors import AuthenticationError, UnsupportedRegion


class FakeResponse:
    status_code = 200

    def __init__(self, payload=None, *, text="", content=b"", headers=None, json_error=False):
        self.payload = {} if payload is None else payload
        self.text = text
        self.content = content
        self.headers = headers or {}
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise ValueError("synthetic non-json")
        return self.payload


class FakeTransport:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls = []
        self.last_response_sha256 = None

    def request(self, method, url, purpose, **kwargs):
        self.calls.append((method, url, purpose, kwargs))
        queue = self.responses.get(purpose)
        if not queue:
            raise AssertionError(f"unexpected request purpose: {purpose}")
        return queue.pop(0)


def _patch_encryption(monkeypatch):
    import fusion_solar_py.encryption as encryption

    monkeypatch.setattr(encryption, "get_secure_random", lambda: "nonce")
    monkeypatch.setattr(encryption, "encrypt_password", lambda **kwargs: "encrypted")


def _base_responses(login_responses):
    return {
        "auth.login-page": [FakeResponse()],
        "auth.pubkey": [FakeResponse({"enableEncrypt": True, "timeStamp": "123"})],
        "auth.login-v3": login_responses,
        "auth.session-redirect": [
            FakeResponse(
                headers={"Location": "https://region01eu5.fusionsolar.huawei.com/home"}
            )
        ],
        "session.keepalive": [FakeResponse()],
        "topology.company": [FakeResponse({"data": {"moDn": "synthetic-company"}})],
    }


def test_encrypted_login_redirect_path_succeeds(monkeypatch, tmp_path):
    _patch_encryption(monkeypatch)
    responses = _base_responses(
        [
            FakeResponse(
                {
                    "redirectURL": (
                        "https://region01eu5.fusionsolar.huawei.com/unisess/v1/auth"
                        "?service=%2Fnetecowebext%2Fhome%2Findex.html"
                    )
                }
            )
        ]
    )
    transport = FakeTransport(responses)
    auth = AuthenticatedSession(
        transport,
        "synthetic-user",
        "synthetic-password",
        "region01eu5.fusionsolar.huawei.com",
        work_dir=tmp_path,
    )
    auth.login()
    assert auth.company_dn == "synthetic-company"
    assert auth.username == "" and auth.password == ""
    assert any(call[2] == "auth.login-v3" for call in transport.calls)


def test_wrong_credentials_fail_without_exposing_secret(monkeypatch, tmp_path):
    _patch_encryption(monkeypatch)
    transport = FakeTransport(
        _base_responses(
            [FakeResponse({"errorCode": "401", "errorMsg": "invalid credentials"})]
        )
    )
    auth = AuthenticatedSession(
        transport,
        "synthetic-user",
        "do-not-echo",
        "region01eu5.fusionsolar.huawei.com",
        work_dir=tmp_path,
    )
    with pytest.raises(AuthenticationError) as caught:
        auth.login()
    assert "do-not-echo" not in str(caught.value)


def test_captcha_required_success_then_login(monkeypatch, tmp_path):
    _patch_encryption(monkeypatch)
    responses = _base_responses(
        [
            FakeResponse({"errorCode": "411", "errorMsg": "verification required"}),
            FakeResponse(
                {
                    "redirectURL": (
                        "https://region01eu5.fusionsolar.huawei.com/unisess/v1/auth"
                        "?service=%2Fnetecowebext%2Fhome%2Findex.html"
                    )
                }
            ),
        ]
    )
    responses["auth.captcha-image"] = [FakeResponse(content=b"image")]
    responses["auth.captcha-prevalidate"] = [FakeResponse(text="success")]
    transport = FakeTransport(responses)
    auth = AuthenticatedSession(
        transport,
        "synthetic-user",
        "synthetic-password",
        "region01eu5.fusionsolar.huawei.com",
        captcha_provider=lambda path: "1234" if Path(path).exists() else "",
        work_dir=tmp_path,
    )
    auth.login()
    assert auth.company_dn == "synthetic-company"
    assert not (tmp_path / "captcha.png").exists()


def test_captcha_failure_is_reported_and_file_removed(monkeypatch, tmp_path):
    _patch_encryption(monkeypatch)
    responses = _base_responses(
        [FakeResponse({"errorCode": "411", "errorMsg": "verification required"})]
    )
    responses["auth.captcha-image"] = [FakeResponse(content=b"image")]
    responses["auth.captcha-prevalidate"] = [FakeResponse(text="failure")]
    auth = AuthenticatedSession(
        FakeTransport(responses),
        "synthetic-user",
        "synthetic-password",
        "region01eu5.fusionsolar.huawei.com",
        captcha_provider=lambda _path: "1234",
        work_dir=tmp_path,
    )
    with pytest.raises(AuthenticationError, match="CAPTCHA"):
        auth.login()
    assert not (tmp_path / "captcha.png").exists()


def test_unexpected_session_redirect_path_fails_closed(monkeypatch, tmp_path):
    _patch_encryption(monkeypatch)
    responses = _base_responses(
        [FakeResponse({"redirectURL": "https://region01eu5.fusionsolar.huawei.com/unexpected"})]
    )
    auth = AuthenticatedSession(
        FakeTransport(responses),
        "synthetic-user",
        "synthetic-password",
        "region01eu5.fusionsolar.huawei.com",
        work_dir=tmp_path,
    )
    with pytest.raises(AuthenticationError, match="redirect path"):
        auth.login()


def test_non_json_login_response_fails_closed(monkeypatch, tmp_path):
    _patch_encryption(monkeypatch)
    responses = _base_responses([FakeResponse(json_error=True)])
    auth = AuthenticatedSession(
        FakeTransport(responses),
        "synthetic-user",
        "synthetic-password",
        "region01eu5.fusionsolar.huawei.com",
        work_dir=tmp_path,
    )
    with pytest.raises(AuthenticationError, match="non-JSON"):
        auth.login()


def test_unsupported_region_is_explicit():
    with pytest.raises(UnsupportedRegion, match="unsupported SSO"):
        _login_host_for("region01la5.fusionsolar.huawei.com")

from pathlib import Path

import pytest
import requests

from fusionsolar_readonly_exporter.auth import AuthenticatedSession, _login_host_for
from fusionsolar_readonly_exporter.errors import AuthenticationError, UnsupportedRegion


class FakeResponse:
    status_code = 200

    def __init__(
        self,
        payload=None,
        *,
        text="",
        content=b"",
        headers=None,
        json_error=False,
        cookies=None,
    ):
        self.payload = {} if payload is None else payload
        self.text = text
        self.content = content
        self.headers = headers or {}
        self.json_error = json_error
        self.cookies = requests.cookies.cookiejar_from_dict(cookies or {})

    def json(self):
        if self.json_error:
            raise ValueError("synthetic non-json")
        return self.payload


class FakeTransport:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.calls = []
        self.last_response_sha256 = None
        self.session = requests.Session()

    def request(self, method, url, purpose, **kwargs):
        self.calls.append((method, url, purpose, kwargs))
        queue = self.responses.get(purpose)
        if not queue:
            raise AssertionError(f"unexpected request purpose: {purpose}")
        response = queue.pop(0)
        self.session.cookies.update(response.cookies)
        return response


def _patch_encryption(monkeypatch):
    import fusion_solar_py.encryption as encryption

    monkeypatch.setattr(encryption, "get_secure_random", lambda: "nonce")
    monkeypatch.setattr(encryption, "encrypt_password", lambda **kwargs: "encrypted")


def _base_responses(login_responses, *, redirect_response=None):
    return {
        "auth.login-page": [FakeResponse()],
        "auth.pubkey": [FakeResponse({"enableEncrypt": True, "timeStamp": "123"})],
        "auth.login-v3": login_responses,
        "auth.session-redirect": [
            redirect_response
            or FakeResponse(
                headers={"Location": "https://region01eu5.fusionsolar.huawei.com/home"}
            )
        ],
        "session.check": [FakeResponse({"code": 0})],
        "session.keepalive": [FakeResponse({"code": 0, "payload": "synthetic-roarand"})],
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
    assert auth.auth_phase == "complete"
    assert auth.username == "" and auth.password == ""
    login_call = next(call for call in transport.calls if call[2] == "auth.login-v3")
    assert login_call[3]["json_body"]["multiRegionName"] == ""
    assert login_call[3]["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert transport.session.headers["roarand"] == "synthetic-roarand"


def test_uni_login_requires_and_accepts_dp_session_cookie(monkeypatch, tmp_path):
    _patch_encryption(monkeypatch)
    redirect = FakeResponse(
        headers={"Location": "https://uni002eu5.fusionsolar.huawei.com/home"},
        cookies={"dp-session": "synthetic-session"},
    )
    responses = _base_responses(
        [
            FakeResponse(
                {
                    "errorCode": "470",
                    "respMultiRegionName": [
                        "unused",
                        "/unisess/v1/auth?service=%2Fnetecowebext%2Fhome%2Findex.html",
                    ],
                }
            )
        ],
        redirect_response=redirect,
    )
    transport = FakeTransport(responses)
    auth = AuthenticatedSession(
        transport,
        "synthetic-user",
        "synthetic-password",
        "uni002eu5.fusionsolar.huawei.com",
        work_dir=tmp_path,
    )
    auth.login()
    assert auth.company_dn == "synthetic-company"
    assert transport.session.cookies.get("dp-session") == "synthetic-session"


def test_uni_login_without_dp_session_fails_closed(monkeypatch, tmp_path):
    _patch_encryption(monkeypatch)
    responses = _base_responses(
        [
            FakeResponse(
                {
                    "respMultiRegionName": [
                        "unused",
                        "/unisess/v1/auth?service=%2Fnetecowebext%2Fhome%2Findex.html",
                    ]
                }
            )
        ],
        redirect_response=FakeResponse(
            headers={"Location": "https://uni002eu5.fusionsolar.huawei.com/home"}
        ),
    )
    auth = AuthenticatedSession(
        FakeTransport(responses),
        "synthetic-user",
        "synthetic-password",
        "uni002eu5.fusionsolar.huawei.com",
        work_dir=tmp_path,
    )
    with pytest.raises(AuthenticationError, match="dp-session"):
        auth.login()


def test_browser_session_cookie_restores_without_password_login(tmp_path):
    responses = {
        "session.check": [FakeResponse({"code": 0})],
        "session.keepalive": [FakeResponse({"code": 0, "payload": "synthetic-roarand"})],
        "topology.company": [FakeResponse({"data": {"moDn": "synthetic-company"}})],
    }
    transport = FakeTransport(responses)
    auth = AuthenticatedSession(
        transport,
        "",
        "",
        "uni002eu5.fusionsolar.huawei.com",
        work_dir=tmp_path,
    )
    auth.restore_session_cookie("private-session-cookie")
    assert auth.company_dn == "synthetic-company"
    assert auth.auth_phase == "complete"
    assert all(not call[2].startswith("auth.login") for call in transport.calls)


def test_wrong_credentials_fail_without_exposing_secret(monkeypatch, tmp_path):
    _patch_encryption(monkeypatch)
    failed = FakeResponse({"errorCode": "401", "errorMsg": "invalid credentials"})
    transport = FakeTransport(_base_responses([failed, failed]))
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

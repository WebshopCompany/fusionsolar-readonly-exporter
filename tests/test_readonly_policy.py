import ast
from pathlib import Path

import pytest

from fusionsolar_readonly_exporter.errors import ReadOnlyPolicyViolation
from fusionsolar_readonly_exporter.readonly_transport import (
    RULES,
    ReadOnlyTransport,
)


class RedirectResponse:
    status_code = 302
    headers = {"Location": "https://example.org/unexpected"}

    @staticmethod
    def raise_for_status():
        return None


def test_forbidden_control_path_is_denied_before_network():
    with pytest.raises(ReadOnlyPolicyViolation):
        ReadOnlyTransport.assert_allowed(
            "POST",
            (
                "https://region01eu5.fusionsolar.huawei.com"
                "/rest/pvms/web/device/v1/deviceExt/set-config-signals"
            ),
            "device.control",
            data={"dn": "synthetic", "changeValues": "[]"},
        )


def test_unknown_endpoint_is_denied():
    with pytest.raises(ReadOnlyPolicyViolation):
        ReadOnlyTransport.assert_allowed(
            "GET",
            "https://region01eu5.fusionsolar.huawei.com/rest/unknown",
            "unknown",
        )


def test_allowed_history_request():
    ReadOnlyTransport.assert_allowed(
        "GET",
        ("https://region01eu5.fusionsolar.huawei.com/rest/pvms/web/device/v1/device-history-data"),
        "device.history",
        params={
            "signalIds": ["30007"],
            "deviceDn": "synthetic",
            "date": 1,
            "_": 2,
        },
    )


def test_requests_import_only_in_transport():
    root = Path(__file__).parents[1] / "src" / "fusionsolar_readonly_exporter"
    offenders = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == "requests" for alias in node.names
            ):
                offenders.append(path.name)
            if isinstance(node, ast.ImportFrom) and node.module == "requests":
                offenders.append(path.name)
    assert offenders == ["readonly_transport.py"]


def test_extra_body_key_is_denied():
    with pytest.raises(ReadOnlyPolicyViolation):
        ReadOnlyTransport.assert_allowed(
            "POST",
            "https://eu5.fusionsolar.huawei.com/unisso/v3/validateUser.action",
            "auth.login-v3",
            params={"timeStamp": "1", "nonce": "n"},
            json_body={
                "organizationName": "",
                "username": "synthetic",
                "password": "synthetic",
                "unexpected": "value",
            },
        )


def test_non_huawei_host_is_denied():
    with pytest.raises(ReadOnlyPolicyViolation):
        ReadOnlyTransport.assert_allowed(
            "GET",
            "https://example.org/rest/dpcloud/auth/v1/keep-alive",
            "session.keepalive",
        )


def test_redirect_from_data_endpoint_is_denied_without_following():
    transport = ReadOnlyTransport(delay_seconds=0)
    transport.session.request = lambda *args, **kwargs: RedirectResponse()
    with pytest.raises(ReadOnlyPolicyViolation):
        transport.request(
            "GET",
            "https://region01eu5.fusionsolar.huawei.com/rest/dpcloud/auth/v1/keep-alive",
            "session.keepalive",
            capture=False,
        )


def test_all_rules_are_read_or_query_and_forbidden_path_absent():
    forbidden = ("set-config", "control", "commission", "firmware", "upgrade")
    assert RULES
    for rule in RULES:
        assert not any(fragment in rule.path.lower() for fragment in forbidden)
        if rule.method == "POST":
            assert rule.purpose.startswith(("auth.", "topology.", "alarms."))

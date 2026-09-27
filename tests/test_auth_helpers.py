import pytest

from fusionsolar_readonly_exporter.auth import (
    _eu5_service_value,
    _host_from_multi_region,
    _login_host_for,
    normalize_host,
)


def test_normalize_host_accepts_browser_url_and_username_is_not_constrained():
    assert (
        normalize_host("https://region01eu5.fusionsolar.huawei.com/home")
        == "region01eu5.fusionsolar.huawei.com"
    )
    assert _login_host_for("region01eu5.fusionsolar.huawei.com") == "eu5.fusionsolar.huawei.com"


def test_normalize_host_rejects_non_huawei():
    with pytest.raises(ValueError):
        normalize_host("https://example.org/")


def test_multi_region_redirect_parser():
    host, path, query = _host_from_multi_region(
        "https://region01eu5.fusionsolar.huawei.com/unisess/v1/auth"
        "?service=https%3A%2F%2Fregion01eu5.fusionsolar.huawei.com"
    )
    assert host == "region01eu5.fusionsolar.huawei.com"
    assert path == "/unisess/v1/auth"
    assert "service" in query


def test_modern_service_value_is_nested_session_auth():
    value = _eu5_service_value()
    assert value.startswith("/unisess/v1/auth?")
    assert "netecowebext" in value

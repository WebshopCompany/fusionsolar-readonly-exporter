from types import SimpleNamespace

import pytest

from fusionsolar_readonly_exporter.exporter import _failure_outcome


class SyntheticHttpFailure(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"synthetic HTTP {status_code}")
        self.response = SimpleNamespace(status_code=status_code)


@pytest.mark.parametrize("status_code", [400, 404, 405])
def test_generic_http_capability_failures_are_not_reported_as_unsupported(status_code):
    assert _failure_outcome(SyntheticHttpFailure(status_code)) == "http_api_failure"


@pytest.mark.parametrize("status_code", [401, 403])
def test_authentication_http_failures_remain_permission_issues(status_code):
    assert (
        _failure_outcome(SyntheticHttpFailure(status_code))
        == "authentication_permission_issue"
    )


def test_other_http_failure_remains_explicit_api_failure():
    assert _failure_outcome(SyntheticHttpFailure(500)) == "http_api_failure"

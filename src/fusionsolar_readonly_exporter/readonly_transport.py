from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from .errors import ReadOnlyPolicyViolation

_ALLOWED_HOST_SUFFIX = ".fusionsolar.huawei.com"
_FORBIDDEN_FRAGMENTS = (
    "set-config",
    "setconfig",
    "control",
    "commission",
    "firmware",
    "upgrade",
    "start",
    "stop",
    "delete",
    "update-config",
    "change-config",
    "power-limit",
)


@dataclass(frozen=True)
class Rule:
    method: str
    path: str
    purpose: str
    query_keys: frozenset[str] = frozenset()
    json_keys: frozenset[str] = frozenset()
    form_keys: frozenset[str] = frozenset()


RULES: tuple[Rule, ...] = (
    Rule("GET", "/unisso/login.action", "auth.login-page", frozenset({"service"})),
    Rule("GET", "/unisso/pubkey", "auth.pubkey"),
    Rule("GET", "/unisso/verifycode", "auth.captcha-image", frozenset({"timestamp"})),
    Rule(
        "POST",
        "/unisso/preValidVerifycode",
        "auth.captcha-prevalidate",
        form_keys=frozenset({"verifycode", "index"}),
    ),
    Rule(
        "POST",
        "/unisso/v2/validateUser.action",
        "auth.login-v2",
        frozenset({"decision", "service"}),
        frozenset({"organizationName", "username", "password", "verifycode"}),
    ),
    Rule(
        "POST",
        "/unisso/v3/validateUser.action",
        "auth.login-v3",
        frozenset({"timeStamp", "nonce", "service"}),
        frozenset({"organizationName", "username", "password", "verifycode"}),
    ),
    Rule("GET", "/unisess/v1/auth", "auth.session-redirect", frozenset({"service"})),
    Rule("GET", "/rest/dpcloud/auth/v1/is-session-alive", "session.check"),
    Rule("GET", "/rest/dpcloud/auth/v1/keep-alive", "session.keepalive"),
    Rule(
        "GET",
        "/rest/neteco/web/organization/v2/company/current",
        "topology.company",
        frozenset({"_"}),
    ),
    Rule(
        "POST",
        "/rest/pvms/web/station/v1/station/station-list",
        "topology.plants",
        json_keys=frozenset(
            {
                "curPage",
                "pageSize",
                "gridConnectedTime",
                "queryTime",
                "timeZone",
                "sortId",
                "sortDir",
                "locale",
            }
        ),
    ),
    Rule(
        "GET",
        "/rest/neteco/web/config/device/v1/device-list",
        "topology.devices",
        frozenset({"conditionParams.parentDn", "conditionParams.mocTypes", "_"}),
    ),
    Rule(
        "GET",
        "/rest/pvms/web/station/v1/overview/energy-flow",
        "plant.flow",
        frozenset({"stationDn", "_"}),
    ),
    Rule(
        "GET",
        "/rest/pvms/web/station/v1/overview/energy-balance",
        "plant.balance",
        frozenset({"stationDn", "timeDim", "queryTime", "timeZone", "timeZoneStr", "_"}),
    ),
    Rule(
        "GET",
        "/rest/pvms/web/device/v1/device-history-data",
        "device.history",
        frozenset({"signalIds", "deviceDn", "date", "_"}),
    ),
    Rule(
        "GET",
        "/rest/pvms/web/device/v1/device-realtime-data",
        "device.realtime",
        frozenset({"deviceDn", "_"}),
    ),
    Rule(
        "GET",
        "/rest/pvms/web/device/v1/device-real-kpi",
        "device.kpi",
        frozenset({"deviceDn", "signalIds", "_"}),
    ),
    Rule(
        "GET",
        "/rest/pvms/web/device/v1/query-battery-dc",
        "battery.module",
        frozenset({"sigids", "dn", "moduleId", "_"}),
    ),
    Rule(
        "POST",
        "/rest/pvms/fm/v1/query",
        "alarms.current",
        json_keys=frozenset({"dataType", "domainType", "pageNo", "pageSize", "nativeMeDn"}),
    ),
)

_RULE_MAP = {(rule.method, rule.path, rule.purpose): rule for rule in RULES}


def _safe_subset(actual: dict[str, Any] | None, allowed: frozenset[str], where: str) -> None:
    keys = set((actual or {}).keys())
    unknown = keys - set(allowed)
    if unknown:
        raise ReadOnlyPolicyViolation(f"unexpected {where} keys: {sorted(unknown)}")


class ReadOnlyTransport:
    """Single network boundary; every request is denied unless explicitly allowed."""

    def __init__(
        self,
        delay_seconds: float = 0.25,
        raw_recorder: Callable[..., None] | None = None,
    ):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/153 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
            }
        )
        self.delay_seconds = max(0.0, delay_seconds)
        self.raw_recorder = raw_recorder
        self._last_request = 0.0
        self.last_response_sha256: str | None = None

    @staticmethod
    def assert_allowed(
        method: str,
        url: str,
        purpose: str,
        *,
        params=None,
        json_body=None,
        data=None,
    ) -> Rule:
        parsed = urlparse(url)
        method = method.upper()
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(_ALLOWED_HOST_SUFFIX)
        ):
            raise ReadOnlyPolicyViolation("only HTTPS Huawei FusionSolar hosts are permitted")
        path = parsed.path or "/"
        low = path.lower()
        if any(fragment in low for fragment in _FORBIDDEN_FRAGMENTS):
            raise ReadOnlyPolicyViolation(f"forbidden state-changing path: {path}")
        rule = _RULE_MAP.get((method, path, purpose))
        if not rule:
            raise ReadOnlyPolicyViolation(f"request not allowlisted: {method} {path} [{purpose}]")
        _safe_subset(params, rule.query_keys, "query")
        _safe_subset(json_body, rule.json_keys, "json")
        _safe_subset(data, rule.form_keys, "form")
        return rule

    def request(
        self,
        method: str,
        url: str,
        purpose: str,
        *,
        params=None,
        json_body=None,
        data=None,
        capture: bool = True,
        timeout: float = 30.0,
    ) -> requests.Response:
        self.assert_allowed(
            method,
            url,
            purpose,
            params=params,
            json_body=json_body,
            data=data,
        )
        wait = self.delay_seconds - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        response = self.session.request(
            method.upper(),
            url,
            params=params,
            json=json_body,
            data=data,
            timeout=timeout,
            allow_redirects=False,
        )
        self._last_request = time.monotonic()

        if 300 <= response.status_code < 400 and purpose != "auth.session-redirect":
            raise ReadOnlyPolicyViolation(
                "automatic HTTP redirects are disabled; redirected requests must be "
                "explicitly re-authorised"
            )
        if purpose == "auth.session-redirect" and response.status_code not in {
            200,
            302,
            303,
        }:
            response.raise_for_status()
        else:
            response.raise_for_status()

        self.last_response_sha256 = None
        if capture and self.raw_recorder:
            self.last_response_sha256 = self.raw_recorder(
                method=method.upper(),
                url=url,
                purpose=purpose,
                params=params,
                json_body=json_body,
                data=data,
                response=response,
            )
        return response

    def get_json(self, url: str, purpose: str, **kwargs) -> Any:
        return self.request("GET", url, purpose, **kwargs).json()

    def post_json(self, url: str, purpose: str, **kwargs) -> Any:
        return self.request("POST", url, purpose, **kwargs).json()

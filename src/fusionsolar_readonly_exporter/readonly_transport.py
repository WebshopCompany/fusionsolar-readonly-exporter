from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from .errors import ApiResponseError, ReadOnlyPolicyViolation, SessionExpired

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
_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRYABLE_POST_PURPOSES = frozenset({"topology.plants", "alarms.current"})


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


def _retry_after_seconds(value: str | None, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        return max(0.0, (parsed.astimezone(timezone.utc) - current).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


class ReadOnlyTransport:
    """Single network boundary; every request is denied unless explicitly allowed."""

    def __init__(
        self,
        delay_seconds: float = 0.25,
        raw_recorder: Callable[..., str] | None = None,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        max_backoff: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "fusionsolar-readonly-exporter/0.1",
                "Accept": "application/json, text/plain, */*",
            }
        )
        self.delay_seconds = max(0.0, delay_seconds)
        self.raw_recorder = raw_recorder
        self.connect_timeout = max(0.1, connect_timeout)
        self.read_timeout = max(0.1, read_timeout)
        self.max_retries = max(0, max_retries)
        self.backoff_base = max(0.0, backoff_base)
        self.max_backoff = max(0.0, max_backoff)
        self._sleep = sleep
        self._jitter = jitter
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

    @staticmethod
    def _retryable(rule: Rule) -> bool:
        return rule.method == "GET" or rule.purpose in _RETRYABLE_POST_PURPOSES

    def _backoff(self, attempt: int, response: requests.Response | None = None) -> float:
        if response is not None:
            hinted = _retry_after_seconds(response.headers.get("Retry-After"))
            if hinted is not None:
                return min(self.max_backoff, hinted)
        ceiling = min(self.max_backoff, self.backoff_base * (2**attempt))
        return self._jitter(0.0, ceiling) if ceiling > 0 else 0.0

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
        timeout: tuple[float, float] | None = None,
    ) -> requests.Response:
        rule = self.assert_allowed(
            method,
            url,
            purpose,
            params=params,
            json_body=json_body,
            data=data,
        )
        timeout_value = timeout or (self.connect_timeout, self.read_timeout)
        self.last_response_sha256 = None

        for attempt in range(self.max_retries + 1):
            wait = self.delay_seconds - (time.monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
            try:
                response = self.session.request(
                    rule.method,
                    url,
                    params=params,
                    json=json_body,
                    data=data,
                    timeout=timeout_value,
                    allow_redirects=False,
                )
                self._last_request = time.monotonic()
            except (requests.ConnectionError, requests.Timeout):
                self._last_request = time.monotonic()
                if not self._retryable(rule) or attempt >= self.max_retries:
                    raise
                self._sleep(self._backoff(attempt))
                continue

            if 300 <= response.status_code < 400 and purpose != "auth.session-redirect":
                raise ReadOnlyPolicyViolation(
                    "automatic HTTP redirects are disabled; redirected requests must be "
                    "explicitly re-authorised"
                )

            if response.status_code in {401, 403} and not purpose.startswith("auth."):
                raise SessionExpired(
                    "FusionSolar session is no longer authorised. Re-run the same command "
                    "to authenticate locally and resume the active export."
                )

            if (
                response.status_code in _TRANSIENT_STATUS
                and self._retryable(rule)
                and attempt < self.max_retries
            ):
                self._sleep(self._backoff(attempt, response))
                continue

            response.raise_for_status()
            if capture and self.raw_recorder:
                self.last_response_sha256 = self.raw_recorder(
                    method=rule.method,
                    url=url,
                    purpose=purpose,
                    params=params,
                    json_body=json_body,
                    data=data,
                    response=response,
                )
            return response

        raise RuntimeError("unreachable retry loop")

    def get_json(self, url: str, purpose: str, **kwargs) -> Any:
        response = self.request("GET", url, purpose, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise ApiResponseError(f"{purpose} returned malformed or non-JSON data") from exc

    def post_json(self, url: str, purpose: str, **kwargs) -> Any:
        response = self.request("POST", url, purpose, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise ApiResponseError(f"{purpose} returned malformed or non-JSON data") from exc

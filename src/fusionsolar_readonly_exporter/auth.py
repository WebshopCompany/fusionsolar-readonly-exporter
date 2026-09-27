from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urlparse

from .errors import AuthenticationError, HostDiscoveryRequired, UnsupportedRegion
from .readonly_transport import ReadOnlyTransport

HOST_RE = re.compile(r"^[a-z0-9-]+\.fusionsolar\.huawei\.com$")
_REGION_DATA_RE = re.compile(r"^region\d{2}([a-z][a-z0-9-]*)$")
_UNI_DATA_RE = re.compile(r"^uni\d{3}([a-z][a-z0-9-]*)$")
_UNSUPPORTED_LOGIN_LABELS = frozenset({"la5", "intl"})


def normalize_host(value: str) -> str:
    value = value.strip().lower()
    if "://" in value:
        value = urlparse(value).hostname or ""
    value = value.strip("/")
    if not HOST_RE.fullmatch(value):
        raise ValueError("host must be a Huawei FusionSolar hostname")
    return value


def _login_host_for(data_host: str) -> str:
    host = normalize_host(data_host)
    label = host.split(".", 1)[0]
    match = _REGION_DATA_RE.fullmatch(label) or _UNI_DATA_RE.fullmatch(label)
    if not match:
        raise UnsupportedRegion(
            "Unsupported FusionSolar browser host pattern. Use the region... or supported uni... "
            "hostname shown by the signed-in browser."
        )
    login_label = match.group(1)
    if login_label in _UNSUPPORTED_LOGIN_LABELS:
        raise UnsupportedRegion(
            f"FusionSolar login region '{login_label}' uses an unsupported SSO flow; "
            "no credentials were sent."
        )
    return f"{login_label}.fusionsolar.huawei.com"


def _host_from_multi_region(value: str) -> tuple[str | None, str, dict[str, str]]:
    parsed = urlparse(value)
    query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
    service = query.get("service")
    service_host = urlparse(service).hostname if service and "://" in service else None
    return parsed.hostname or service_host, parsed.path, query


def _service_value() -> str:
    return "/unisess/v1/auth?service=%2Fnetecowebext%2Fhome%2Findex.html"


def _eu5_service_value() -> str:
    return _service_value()


def _is_uni_host(host: str) -> bool:
    return normalize_host(host).split(".", 1)[0].startswith("uni")


class AuthenticatedSession:
    def __init__(
        self,
        transport: ReadOnlyTransport,
        username: str,
        password: str,
        data_host: str,
        captcha_provider: Callable[[Path], str] | None = None,
        work_dir: Path | None = None,
    ):
        if not data_host:
            raise HostDiscoveryRequired(
                "A FusionSolar browser host is required before credentials can be sent."
            )
        self.transport = transport
        self.username = username
        self.password = password
        self.data_host = normalize_host(data_host)
        self.initial_data_host = self.data_host
        self.login_host = _login_host_for(self.data_host)
        self.captcha_provider = captcha_provider
        self.work_dir = work_dir or Path.cwd()
        self.company_dn: str | None = None
        self.auth_phase = "not-started"

    def _set_auth_phase(self, phase: str) -> None:
        self.auth_phase = phase

    def _browser_headers(self, *, referer: str) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Origin": f"https://{self.login_host}",
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
        }

    def _captcha(self) -> str:
        self._set_auth_phase("captcha")
        if not self.captcha_provider:
            raise AuthenticationError(
                "FusionSolar requires a CAPTCHA; no local CAPTCHA provider is configured"
            )
        image = self.transport.request(
            "GET",
            f"https://{self.login_host}/unisso/verifycode",
            "auth.captcha-image",
            params={"timestamp": __import__("time").time_ns() // 1_000_000},
            capture=False,
        ).content
        self.work_dir.mkdir(parents=True, exist_ok=True)
        path = self.work_dir / "captcha.png"
        path.write_bytes(image)
        try:
            os.chmod(path, 0o600)
        except (OSError, NotImplementedError):
            pass
        try:
            code = self.captcha_provider(path).strip()
            if not code:
                raise AuthenticationError("empty CAPTCHA code")
            check = self.transport.request(
                "POST",
                f"https://{self.login_host}/unisso/preValidVerifycode",
                "auth.captcha-prevalidate",
                data={"verifycode": code, "index": 0},
                capture=False,
            )
            if check.text.strip().strip('"').lower() != "success":
                raise AuthenticationError("FusionSolar rejected the CAPTCHA code")
            return code
        finally:
            path.unlink(missing_ok=True)

    def _session_redirect(self, value: str) -> None:
        self._set_auth_phase("session-redirect")
        discovered, redirect_path, redirect_query = _host_from_multi_region(value)
        if redirect_path != "/unisess/v1/auth":
            raise AuthenticationError("unexpected FusionSolar session redirect path")
        try:
            target_host = normalize_host(discovered or self.login_host)
        except ValueError as exc:
            raise AuthenticationError(
                "FusionSolar session redirect targeted an invalid host"
            ) from exc
        response = self.transport.request(
            "GET",
            f"https://{target_host}{redirect_path}",
            "auth.session-redirect",
            params=redirect_query,
            capture=False,
        )
        location = response.headers.get("Location") or ""
        location_host = urlparse(location).hostname
        candidate = location_host or discovered or self.data_host
        try:
            candidate = normalize_host(candidate)
            _login_host_for(candidate)
        except (ValueError, HostDiscoveryRequired) as exc:
            raise AuthenticationError(
                "FusionSolar session redirect targeted an unsupported host"
            ) from exc
        self.data_host = candidate
        if _is_uni_host(self.initial_data_host):
            dp_session = response.cookies.get("dp-session") or self.transport.session.cookies.get(
                "dp-session"
            )
            if not dp_session:
                raise AuthenticationError("FusionSolar session redirect did not establish dp-session")

    @staticmethod
    def _json_object(response, purpose: str) -> dict:
        try:
            body = response.json()
        except ValueError as exc:
            raise AuthenticationError(f"FusionSolar returned non-JSON data for {purpose}") from exc
        if not isinstance(body, dict):
            raise AuthenticationError(f"FusionSolar returned an unexpected schema for {purpose}")
        return body

    def restore_session_cookie(self, dp_session: str) -> None:
        """Use an owner-supplied existing browser session without persisting the cookie."""
        cookie = dp_session.strip()
        if not cookie:
            raise AuthenticationError("empty FusionSolar browser session cookie")
        self._set_auth_phase("browser-session")
        self.transport.session.cookies.set("dp-session", cookie)
        self.transport.session.cookies.set("locale", "en-us")
        try:
            self._validate_data_host()
        finally:
            dp_session = ""
            cookie = ""
        self._clear_credentials()

    def login(self) -> None:
        try:
            from fusion_solar_py.encryption import encrypt_password, get_secure_random
        except ImportError as exc:
            raise AuthenticationError(
                "fusion-solar-py 0.1.2 is required for authentication"
            ) from exc

        self._set_auth_phase("login-page")
        service_value = _service_value()
        encoded_service = quote(service_value, safe="")
        login_page_url = f"https://{self.login_host}/unisso/login.action?service={encoded_service}"
        self.transport.request(
            "GET",
            f"https://{self.login_host}/unisso/login.action",
            "auth.login-page",
            params={"service": service_value},
            capture=False,
        )

        self._set_auth_phase("pubkey")
        key_response = self.transport.request(
            "GET",
            f"https://{self.login_host}/unisso/pubkey",
            "auth.pubkey",
            capture=False,
        )
        key = self._json_object(key_response, "auth.pubkey")
        encrypted = bool(key.get("enableEncrypt"))
        if encrypted and not key.get("timeStamp"):
            raise AuthenticationError("FusionSolar encrypted-login response omitted timeStamp")

        captcha_code: str | None = None
        for captcha_round in range(2):
            service_modes = (True, False) if encrypted else (False,)
            last_error = ""
            last_error_code = ""
            captcha_required = False
            for use_service in service_modes:
                self._set_auth_phase("credential-submit")
                params: dict[str, object] = {}
                password = self.password
                if encrypted:
                    path = "/unisso/v3/validateUser.action"
                    purpose = "auth.login-v3"
                    params = {"timeStamp": key["timeStamp"], "nonce": get_secure_random()}
                    if use_service:
                        params["service"] = service_value
                    try:
                        password = encrypt_password(key_data=key, password=self.password)
                    except Exception as exc:
                        raise AuthenticationError(
                            "FusionSolar password encryption could not be prepared safely"
                        ) from exc
                else:
                    path = "/unisso/v2/validateUser.action"
                    purpose = "auth.login-v2"
                    params = {
                        "decision": 1,
                        "service": (
                            f"https://{self.data_host}/unisess/v1/auth?"
                            "service=/netecowebext/home/index.html#/LOGIN"
                        ),
                    }
                payload = {
                    "organizationName": "",
                    "username": self.username,
                    "password": password,
                    "multiRegionName": "",
                }
                if captcha_code:
                    payload["verifycode"] = captcha_code
                response = self.transport.request(
                    "POST",
                    f"https://{self.login_host}{path}",
                    purpose,
                    params=params,
                    json_body=payload,
                    headers=self._browser_headers(referer=login_page_url),
                    capture=False,
                )
                body = self._json_object(response, purpose)
                regions = body.get("respMultiRegionName") or []
                if regions is not None and not isinstance(regions, list):
                    raise AuthenticationError(
                        "FusionSolar returned malformed multi-region metadata"
                    )
                redirect_value = None
                if isinstance(regions, list) and len(regions) > 1:
                    redirect_value = str(regions[1])
                elif body.get("redirectURL"):
                    redirect_value = str(body["redirectURL"])
                if redirect_value:
                    self._session_redirect(redirect_value)
                    self._validate_data_host()
                    self._clear_credentials()
                    return
                last_error_code = str(body.get("errorCode") or "")
                last_error = str(body.get("errorMsg") or "")
                captcha_required = bool(
                    last_error_code == "411"
                    or body.get("verifyCodeCreate")
                    or "verification" in last_error.lower()
                    or "captcha" in last_error.lower()
                )
                if captcha_required:
                    break
                if use_service:
                    continue
                if last_error_code or last_error:
                    message = last_error or f"error code {last_error_code}"
                    raise AuthenticationError(f"FusionSolar login failed: {message}")
            if captcha_required and captcha_round == 0:
                captcha_code = self._captcha()
                continue
            if captcha_required:
                raise AuthenticationError(
                    "FusionSolar login still requires a CAPTCHA after validation"
                )
            if last_error or last_error_code:
                message = last_error or f"error code {last_error_code}"
                raise AuthenticationError(f"FusionSolar login failed: {message}")
            break

        # Legacy/non-redirect flows can establish the session directly during credential
        # submission. Validate that session explicitly rather than assuming redirect metadata.
        self._validate_data_host()
        self._clear_credentials()

    def _clear_credentials(self) -> None:
        self.username = ""
        self.password = ""

    def _validate_data_host(self) -> None:
        self._set_auth_phase("session-validation")
        try:
            alive_response = self.transport.request(
                "GET",
                f"https://{self.data_host}/rest/dpcloud/auth/v1/is-session-alive",
                "session.check",
                capture=False,
            )
            alive = self._json_object(alive_response, "session.check")
            if alive.get("code") != 0:
                raise AuthenticationError("FusionSolar browser session is not active")

            keep_alive = self.transport.request(
                "GET",
                f"https://{self.data_host}/rest/dpcloud/auth/v1/keep-alive",
                "session.keepalive",
                capture=False,
            )
            keep_alive_body = self._json_object(keep_alive, "session.keepalive")
            if keep_alive_body.get("code") not in (None, 0):
                raise AuthenticationError("FusionSolar keep-alive rejected the session")
            payload = keep_alive_body.get("payload")
            if payload:
                self.transport.session.headers["roarand"] = str(payload)

            self._set_auth_phase("company-discovery")
            company_response = self.transport.request(
                "GET",
                f"https://{self.data_host}/rest/neteco/web/organization/v2/company/current",
                "topology.company",
                params={"_": __import__("time").time_ns() // 1_000_000},
                capture=False,
            )
            company = self._json_object(company_response, "topology.company")
        except AuthenticationError:
            raise
        except Exception as exc:
            raise HostDiscoveryRequired(
                "FusionSolar could not safely validate the supplied data host. Re-check the "
                "hostname shown in the signed-in browser."
            ) from exc
        data = company.get("data")
        if not isinstance(data, dict) or not data.get("moDn"):
            raise HostDiscoveryRequired("FusionSolar did not return the current company identifier")
        self.company_dn = str(data["moDn"])
        self._set_auth_phase("complete")

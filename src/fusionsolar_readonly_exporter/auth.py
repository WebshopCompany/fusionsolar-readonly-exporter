from __future__ import annotations

import re
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .errors import AuthenticationError, HostDiscoveryRequired
from .readonly_transport import ReadOnlyTransport

HOST_RE = re.compile(r"^[a-z0-9-]+\.fusionsolar\.huawei\.com$")


def normalize_host(value: str) -> str:
    value = value.strip().lower()
    if "://" in value:
        value = urlparse(value).hostname or ""
    value = value.strip("/")
    if not HOST_RE.fullmatch(value):
        raise ValueError("host must be a Huawei FusionSolar hostname")
    return value


def _login_host_for(data_host: str) -> str:
    label = data_host.split(".", 1)[0]
    if label.startswith("region") and len(label) > 8:
        label = label[8:]
    elif label.startswith("uni") and len(label) > 6:
        label = label[6:]
    return f"{label}.fusionsolar.huawei.com"


def _host_from_multi_region(value: str) -> tuple[str | None, str, dict[str, str]]:
    parsed = urlparse(value)
    query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
    service = query.get("service")
    service_host = urlparse(service).hostname if service and "://" in service else None
    return parsed.hostname or service_host, parsed.path, query


def _eu5_service_value() -> str:
    return "/unisess/v1/auth?service=%2Fnetecowebext%2Fhome%2Findex.html"


class AuthenticatedSession:
    def __init__(
        self,
        transport: ReadOnlyTransport,
        username: str,
        password: str,
        data_host: str | None = None,
        captcha_provider: Callable[[Path], str] | None = None,
        work_dir: Path | None = None,
    ):
        self.transport = transport
        self.username = username
        self.password = password
        self.data_host = (
            normalize_host(data_host) if data_host else "region01eu5.fusionsolar.huawei.com"
        )
        self.login_host = _login_host_for(self.data_host)
        self.captcha_provider = captcha_provider
        self.work_dir = work_dir or Path.cwd()
        self.company_dn: str | None = None

    def _captcha(self) -> str:
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
        path = self.work_dir / "captcha.png"
        path.write_bytes(image)
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
        discovered, redirect_path, redirect_query = _host_from_multi_region(value)
        if redirect_path != "/unisess/v1/auth":
            raise AuthenticationError("unexpected FusionSolar session redirect path")

        target_host = discovered or self.login_host
        response = self.transport.request(
            "GET",
            f"https://{target_host}{redirect_path}",
            "auth.session-redirect",
            params=redirect_query,
            capture=False,
        )

        location = response.headers.get("Location") or ""
        location_host = urlparse(location).hostname
        candidate = location_host or discovered
        if candidate:
            candidate = normalize_host(candidate)
            self.data_host = candidate

    def login(self) -> None:
        if self.login_host.split(".", 1)[0] in {"la5", "intl"}:
            raise HostDiscoveryRequired(
                "This FusionSolar login region uses a different SSO flow that is not "
                "enabled in this exporter yet. No credentials were sent to guessed regions."
            )

        try:
            from fusion_solar_py.encryption import encrypt_password, get_secure_random
        except ImportError as exc:
            raise AuthenticationError(
                "fusion-solar-py 0.1.2 is required for authentication"
            ) from exc

        service_value = _eu5_service_value()
        self.transport.request(
            "GET",
            f"https://{self.login_host}/unisso/login.action",
            "auth.login-page",
            params={"service": service_value},
            capture=False,
        )

        key_response = self.transport.request(
            "GET",
            f"https://{self.login_host}/unisso/pubkey",
            "auth.pubkey",
            capture=False,
        )
        key = key_response.json()
        captcha_code: str | None = None
        encrypted = bool(key.get("enableEncrypt"))

        for captcha_round in range(2):
            service_modes = (True, False) if encrypted else (False,)
            last_error = ""
            captcha_required = False

            for use_service in service_modes:
                params: dict[str, object] = {}
                password = self.password

                if encrypted:
                    path = "/unisso/v3/validateUser.action"
                    purpose = "auth.login-v3"
                    params = {
                        "timeStamp": key["timeStamp"],
                        "nonce": get_secure_random(),
                    }
                    if use_service:
                        params["service"] = service_value
                    password = encrypt_password(key_data=key, password=self.password)
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
                }
                if captcha_code:
                    payload["verifycode"] = captcha_code

                response = self.transport.request(
                    "POST",
                    f"https://{self.login_host}{path}",
                    purpose,
                    params=params,
                    json_body=payload,
                    capture=False,
                )
                try:
                    body = response.json()
                except ValueError as exc:
                    raise AuthenticationError(
                        "FusionSolar returned a non-JSON login response"
                    ) from exc

                regions = body.get("respMultiRegionName") or []
                redirect_value = None
                if len(regions) > 1:
                    redirect_value = str(regions[1])
                elif body.get("redirectURL"):
                    redirect_value = str(body["redirectURL"])

                if redirect_value:
                    self._session_redirect(redirect_value)
                    self._validate_data_host()
                    self.username = ""
                    self.password = ""
                    return

                error_code = str(body.get("errorCode") or "")
                last_error = str(body.get("errorMsg") or "")
                captcha_required = bool(
                    error_code == "411"
                    or body.get("verifyCodeCreate")
                    or "verification" in last_error.lower()
                )
                if captcha_required:
                    break

                if error_code == "406" and use_service:
                    continue
                if last_error and not use_service:
                    raise AuthenticationError(f"FusionSolar login failed: {last_error}")

            if captcha_required and captcha_round == 0:
                captcha_code = self._captcha()
                continue
            if captcha_required:
                raise AuthenticationError(
                    "FusionSolar login still requires a CAPTCHA after validation"
                )
            if last_error:
                raise AuthenticationError(f"FusionSolar login failed: {last_error}")
            break

        self._validate_data_host()
        self.username = ""
        self.password = ""

    def _validate_data_host(self) -> None:
        try:
            keep_alive = self.transport.request(
                "GET",
                f"https://{self.data_host}/rest/dpcloud/auth/v1/keep-alive",
                "session.keepalive",
                capture=False,
            )
            if keep_alive.status_code != 200:
                raise HostDiscoveryRequired("FusionSolar data host validation failed")
            company = self.transport.request(
                "GET",
                (f"https://{self.data_host}/rest/neteco/web/organization/v2/company/current"),
                "topology.company",
                params={"_": __import__("time").time_ns() // 1_000_000},
                capture=False,
            ).json()
        except Exception as exc:
            raise HostDiscoveryRequired(
                "Automatic host discovery could not safely validate the data host. "
                "Re-run with --host using the FusionSolar hostname visible in the browser."
            ) from exc
        data = company.get("data") if isinstance(company, dict) else None
        if not isinstance(data, dict) or not data.get("moDn"):
            raise HostDiscoveryRequired("FusionSolar did not return the current company identifier")
        self.company_dn = str(data["moDn"])

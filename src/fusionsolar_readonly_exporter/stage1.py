from __future__ import annotations

import argparse
import getpass
import os
import re
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .auth import AuthenticatedSession, _login_host_for, normalize_host
from .client import FusionSolarReadClient
from .errors import ExporterError, HostDiscoveryRequired
from .readonly_transport import ReadOnlyTransport

_SAFE_CLASS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_PHASE_RE = re.compile(r"^[a-z0-9-]+$")


def _host_pattern_class(host: str) -> str:
    try:
        normalized = normalize_host(host)
    except ValueError:
        return "unknown"
    label = normalized.split(".", 1)[0]
    if label.startswith("region"):
        return "region"
    if label.startswith("uni"):
        return "uni"
    return "other"


def _identifier(item: dict[str, Any]) -> str | None:
    for key in ("dn", "deviceDn", "id"):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _coarse_device_class(device: dict[str, Any]) -> str:
    text = " ".join(
        str(device.get(key, "")) for key in ("mocTypeName", "name", "devType", "type")
    ).lower()
    if "battery" in text or "energy storage" in text or "storage" in text:
        return "battery"
    if "inverter" in text:
        return "inverter"
    if "meter" in text or "power sensor" in text or "sensor" in text:
        return "meter"
    return "device"


def _error_class(exc: BaseException) -> str:
    name = type(exc).__name__
    return name if _SAFE_CLASS_RE.fullmatch(name) else "Error"


def _auth_phase(auth: AuthenticatedSession | None) -> str:
    value = getattr(auth, "auth_phase", "unknown") if auth is not None else "unknown"
    return value if isinstance(value, str) and _SAFE_PHASE_RE.fullmatch(value) else "unknown"


def _http_status_class(exc: BaseException) -> str:
    current: BaseException | None = exc
    for _ in range(3):
        response = getattr(current, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int) and 100 <= status <= 599:
            return f"{status // 100}xx"
        cause = getattr(current, "__cause__", None)
        current = cause if isinstance(cause, BaseException) else None
        if current is None:
            break
    return "NONE"


def _emit_safety_footer(
    output: Callable[[str], None],
    *,
    captcha_occurred: bool,
    session_established: bool,
    result: str,
) -> None:
    output(f"CAPTCHA_HANDLING_OCCURRED: {'YES' if captcha_occurred else 'NO'}")
    output(f"SESSION_ESTABLISHED: {'YES' if session_established else 'NO'}")
    output("HISTORICAL_REQUESTS: 0")
    output("BACKFILL_STARTED: NO")
    output(f"STAGE1_RESULT: {result}")


def run_stage1(
    host: str,
    username: str,
    password: str,
    *,
    session_cookie: str | None = None,
    work_dir: Path = Path(".stage1-private"),
    request_delay: float = 0.25,
    connect_timeout: float = 5.0,
    read_timeout: float = 30.0,
    max_retries: int = 3,
    output: Callable[[str], None] = print,
    captcha_reader: Callable[[str], str] = input,
) -> int:
    """Run the bounded owner compatibility check without historical acquisition."""
    output(f"STAGE1_VALIDATOR_VERSION: {__version__}")
    output(f"HOST_PATTERN_CLASS: {_host_pattern_class(host)}")

    try:
        normalized_host = normalize_host(host)
        _login_host_for(normalized_host)
    except (ValueError, HostDiscoveryRequired) as exc:
        output("HOST_VALIDATION: FAIL")
        output("AUTHENTICATION: NOT_ATTEMPTED")
        output("AUTH_METHOD: NONE")
        output("AUTH_PHASE: host-validation")
        output(f"ERROR_CLASS: {_error_class(exc)}")
        output("HTTP_STATUS_CLASS: NONE")
        _emit_safety_footer(
            output, captcha_occurred=False, session_established=False, result="FAIL"
        )
        return 3

    output("HOST_VALIDATION: PASS")
    use_session_cookie = bool(session_cookie)
    output(f"AUTH_METHOD: {'BROWSER_SESSION' if use_session_cookie else 'PASSWORD'}")
    if not use_session_cookie and (not username or not password):
        output("AUTHENTICATION: NOT_ATTEMPTED")
        output("AUTH_PHASE: local-input")
        output("ERROR_CLASS: MissingLocalCredentials")
        output("HTTP_STATUS_CLASS: NONE")
        _emit_safety_footer(
            output, captcha_occurred=False, session_established=False, result="FAIL"
        )
        return 2

    captcha_occurred = False
    session_established = False
    auth: AuthenticatedSession | None = None

    def captcha_provider(_path: Path) -> str:
        nonlocal captcha_occurred
        captcha_occurred = True
        output("CAPTCHA_REQUIRED: YES")
        output("CAPTCHA_LOCATION: LOCAL_PRIVATE_WORK_DIRECTORY")
        return captcha_reader("CAPTCHA code: ")

    work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(work_dir, 0o700)
    except (OSError, NotImplementedError):
        pass

    transport = ReadOnlyTransport(
        delay_seconds=request_delay,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        max_retries=max_retries,
    )
    try:
        auth = AuthenticatedSession(
            transport,
            username,
            password,
            data_host=normalized_host,
            captcha_provider=captcha_provider,
            work_dir=work_dir,
        )
        if use_session_cookie:
            auth.restore_session_cookie(session_cookie or "")
        else:
            auth.login()
        session_established = True
        output("AUTHENTICATION: PASS")
        output(f"AUTH_PHASE: {_auth_phase(auth)}")

        client = FusionSolarReadClient(auth)
        plants = client.plants()
        output(f"PLANT_COUNT: {len(plants)}")

        discovered: list[dict[str, Any]] = []
        for plant in plants:
            plant_dn = _identifier(plant)
            if plant_dn:
                discovered.extend(client.devices(plant_dn))
        if not discovered:
            discovered = client.devices()

        devices: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for device in discovered:
            device_dn = _identifier(device)
            if device_dn and device_dn in seen_ids:
                continue
            if device_dn:
                seen_ids.add(device_dn)
            devices.append(device)

        output(f"DEVICE_COUNT: {len(devices)}")
        classes = sorted({_coarse_device_class(device) for device in devices})
        output(f"DEVICE_CLASSES: {','.join(classes) if classes else 'none'}")

        realtime_target = next(
            (device_dn for device in devices if (device_dn := _identifier(device))),
            None,
        )
        if realtime_target is None:
            output("REALTIME_READ: SKIPPED_NO_DEVICE_ID")
            output("ERROR_CLASS: TopologyEmptyOrUnaddressable")
            output("HTTP_STATUS_CLASS: NONE")
            _emit_safety_footer(
                output,
                captcha_occurred=captcha_occurred,
                session_established=session_established,
                result="FAIL",
            )
            return 1

        client.realtime(realtime_target)
        output("REALTIME_READ: PASS")
        _emit_safety_footer(
            output,
            captcha_occurred=captcha_occurred,
            session_established=session_established,
            result="PASS",
        )
        return 0
    except ExporterError as exc:
        output("AUTHENTICATION: FAIL" if not session_established else "STAGE1_OPERATION: FAIL")
        output(f"AUTH_PHASE: {_auth_phase(auth)}")
        output(f"ERROR_CLASS: {_error_class(exc)}")
        output(f"HTTP_STATUS_CLASS: {_http_status_class(exc)}")
        _emit_safety_footer(
            output,
            captcha_occurred=captcha_occurred,
            session_established=session_established,
            result="FAIL",
        )
        return 1
    except Exception as exc:
        output("AUTHENTICATION: FAIL" if not session_established else "STAGE1_OPERATION: FAIL")
        output(f"AUTH_PHASE: {_auth_phase(auth)}")
        output(f"ERROR_CLASS: {_error_class(exc)}")
        output(f"HTTP_STATUS_CLASS: {_http_status_class(exc)}")
        _emit_safety_footer(
            output,
            captcha_occurred=captcha_occurred,
            session_established=session_established,
            result="FAIL",
        )
        return 1
    finally:
        if auth is not None:
            auth.username = ""
            auth.password = ""
        username = ""
        password = ""
        session_cookie = ""


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Read-only FusionSolar Stage-1 compatibility validator (no history/backfill)"
    )
    p.add_argument("--host", help="FusionSolar browser host or URL; prompted locally if omitted")
    p.add_argument(
        "--use-browser-session",
        action="store_true",
        help="prompt locally for an existing dp-session cookie instead of username/password",
    )
    p.add_argument("--work-dir", type=Path, default=Path(".stage1-private"))
    p.add_argument(
        "--request-delay",
        type=float,
        default=float(os.getenv("FUSIONSOLAR_REQUEST_DELAY_SECONDS", "0.25")),
    )
    p.add_argument(
        "--connect-timeout",
        type=float,
        default=float(os.getenv("FUSIONSOLAR_CONNECT_TIMEOUT_SECONDS", "5")),
    )
    p.add_argument(
        "--read-timeout",
        type=float,
        default=float(os.getenv("FUSIONSOLAR_READ_TIMEOUT_SECONDS", "30")),
    )
    p.add_argument(
        "--max-retries",
        type=int,
        default=int(os.getenv("FUSIONSOLAR_MAX_RETRIES", "3")),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    host = (args.host or input("FusionSolar browser host or URL: ")).strip()
    try:
        normalized_host = normalize_host(host)
        _login_host_for(normalized_host)
    except (ValueError, HostDiscoveryRequired):
        return run_stage1(
            host,
            "",
            "",
            work_dir=args.work_dir,
            request_delay=args.request_delay,
            connect_timeout=args.connect_timeout,
            read_timeout=args.read_timeout,
            max_retries=args.max_retries,
        )

    username = ""
    password = ""
    session_cookie = ""
    if args.use_browser_session:
        session_cookie = getpass.getpass("FusionSolar dp-session cookie (hidden input): ")
    else:
        username = input("FusionSolar username: ").strip()
        password = getpass.getpass("FusionSolar password: ")
    try:
        return run_stage1(
            normalized_host,
            username,
            password,
            session_cookie=session_cookie or None,
            work_dir=args.work_dir,
            request_delay=args.request_delay,
            connect_timeout=args.connect_timeout,
            read_timeout=args.read_timeout,
            max_retries=args.max_retries,
        )
    finally:
        username = ""
        password = ""
        session_cookie = ""

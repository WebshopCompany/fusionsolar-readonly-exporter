from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from .auth import AuthenticatedSession
from .client import FusionSolarReadClient
from .errors import ExporterError, HostDiscoveryRequired
from .exporter import Exporter
from .readonly_transport import ReadOnlyTransport
from .storage import RunStore


def _captcha_provider(path: Path) -> str:
    print(f"FusionSolar CAPTCHA required. Open locally: {path}")
    return input("CAPTCHA code: ")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Strictly read-only Huawei FusionSolar owner-account exporter"
    )
    p.add_argument(
        "--host",
        help="FusionSolar browser data host; only needed if safe auto-discovery cannot validate it",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="ignore incremental watermark and re-probe full available history",
    )
    p.add_argument("--output-dir", type=Path, default=Path("output"))
    p.add_argument("--state-dir", type=Path, default=Path("state"))
    p.add_argument("--overlap-days", type=int, default=2)
    p.add_argument(
        "--request-delay",
        type=float,
        default=float(os.getenv("FUSIONSOLAR_REQUEST_DELAY_SECONDS", "0.25")),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    username = input("FusionSolar username: ").strip()
    password = getpass.getpass("FusionSolar password: ")
    if not username or not password:
        print("Username and password are required locally.")
        return 2
    store = RunStore.create(args.output_dir, args.state_dir)
    transport = ReadOnlyTransport(
        delay_seconds=args.request_delay, raw_recorder=store.record_exchange
    )
    auth = AuthenticatedSession(
        transport,
        username,
        password,
        data_host=args.host,
        captcha_provider=_captcha_provider,
        work_dir=args.state_dir,
    )
    try:
        print("Authenticating...")
        auth.login()
        client = FusionSolarReadClient(auth)
        Exporter(client, store, full=args.full, overlap_days=args.overlap_days).run()
        return 0
    except HostDiscoveryRequired as exc:
        print(str(exc))
        return 3
    except ExporterError as exc:
        print(f"FusionSolar export failed safely: {exc}")
        return 1
    finally:
        password = ""
        username = ""

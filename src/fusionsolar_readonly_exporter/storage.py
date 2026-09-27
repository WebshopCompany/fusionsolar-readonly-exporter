from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import secrets
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SECRET_KEYS = {
    "password",
    "username",
    "verifycode",
    "cookie",
    "cookies",
    "token",
    "authorization",
    "csrf",
    "xsrf",
    "session",
    "sessionid",
    "jsessionid",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("<redacted>" if k.lower() in SECRET_KEYS else _redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


@dataclass
class RunStore:
    root: Path
    state_root: Path
    raw_index: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(cls, output_root: Path, state_root: Path) -> "RunStore":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        root = output_root / f"fusionsolar-export-{stamp}"
        for name in ("raw", "normalised", "derived", "validation"):
            (root / name).mkdir(parents=True, exist_ok=True)
        state_root.mkdir(parents=True, exist_ok=True)
        return cls(root=root, state_root=state_root)

    def record_exchange(
        self, *, method: str, url: str, purpose: str, params, json_body, data, response
    ) -> str:
        """Persist an exact non-auth response body plus a sanitised request envelope.

        Authentication calls are made with capture=False by the caller. No headers or cookie jar are
        accepted by this method, so they cannot accidentally enter raw custody.
        """
        content = response.content
        raw_hash = sha256_bytes(content)
        seq = len(self.raw_index) + 1
        stem = f"{seq:06d}_{purpose.replace('.', '_')}"
        try:
            response.json()
            extension = ".json"
        except (ValueError, json.JSONDecodeError):
            extension = ".body"
        body_path = self.root / "raw" / f"{stem}{extension}"
        body_path.write_bytes(content)
        parsed = urlparse(url)
        envelope = {
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "method": method,
            "host": parsed.hostname,
            "path": parsed.path,
            "purpose": purpose,
            "params": _redact(params or {}),
            "json_body": _redact(json_body or {}),
            "form": _redact(data or {}),
            "status_code": response.status_code,
            "response_sha256": raw_hash,
            "body_file": body_path.name,
        }
        env_path = self.root / "raw" / f"{stem}.envelope.json"
        env_path.write_text(json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8")
        self.raw_index.append(envelope)
        with (self.root / "raw" / "index.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(envelope, sort_keys=True) + "\n")
        return raw_hash

    def state(self) -> dict[str, Any]:
        path = self.state_root / "state.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def save_state(self, state: dict[str, Any]) -> None:
        path = self.state_root / "state.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    def pseudonym(self, raw_id: str) -> str:
        state = self.state()
        salt_hex = state.get("pseudonym_salt")
        if not salt_hex:
            salt_hex = secrets.token_hex(32)
            state["pseudonym_salt"] = salt_hex
            self.save_state(state)
        digest = hmac.new(bytes.fromhex(salt_hex), raw_id.encode(), hashlib.sha256).hexdigest()
        return "dev-" + digest[:16]

    def write_table(self, relative_stem: str, rows: list[dict[str, Any]]) -> tuple[Path, Path]:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError("pyarrow is required to create the mandated Parquet export") from exc

        csv_path = self.root / f"{relative_stem}.csv"
        pq_path = self.root / f"{relative_stem}.parquet"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        if rows:
            columns = sorted({k for row in rows for k in row.keys()})
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
            pq.write_table(pa.Table.from_pylist(rows), pq_path)
        else:
            csv_path.write_text("", encoding="utf-8")
            pq.write_table(pa.table({"empty": pa.array([], type=pa.string())}), pq_path)
        return csv_path, pq_path

    def manifest(self, extra: dict[str, Any]) -> dict[str, Any]:
        files = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(".zip"):
                files.append(
                    {
                        "path": str(path.relative_to(self.root)),
                        "size": path.stat().st_size,
                        "sha256": sha256_bytes(path.read_bytes()),
                    }
                )
        manifest = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "interface": "Huawei FusionSolar owner-account web/frontend interface (not Northbound/OpenAPI)",
            "evidence_class": "EXTERNAL OWNER-AUTHORISED OBSERVATIONAL TELEMETRY",
            "station_timezone": "Europe/London",
            "canonical_timestamp_timezone": "UTC",
            "files": files,
            **extra,
        }
        (self.root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        return manifest

    def package_zip(self) -> Path:
        zip_path = self.root.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.root.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=str(path.relative_to(self.root)))
        return zip_path

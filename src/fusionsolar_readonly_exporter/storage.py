from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import secrets
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
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


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        pass


def _secure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(path, 0o700)


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _write_json_private(path: Path, value: dict[str, Any]) -> None:
    _secure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    _chmod_best_effort(tmp, 0o600)
    tmp.replace(path)
    _chmod_best_effort(path, 0o600)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("<redacted>" if k.lower() in SECRET_KEYS else _redact(v))
            for k, v in value.items()
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
        output_root = output_root.expanduser()
        state_root = state_root.expanduser()
        _secure_dir(output_root)
        _secure_dir(state_root)

        state_path = state_root / "state.json"
        state = _read_json_object(state_path)
        root: Path | None = None
        active = state.get("active_run_root")
        if isinstance(active, str) and active:
            try:
                candidate = Path(active).expanduser().resolve()
                candidate.relative_to(output_root.resolve())
            except (OSError, ValueError):
                candidate = None
            if candidate is not None and candidate.is_dir():
                root = candidate

        if root is None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ%f")
            root = output_root / f"fusionsolar-export-{stamp}"
            state["active_run_root"] = str(root.resolve())
            state["resource_days"] = {}
            _write_json_private(state_path, state)

        for path in (
            root,
            root / "raw",
            root / "normalised",
            root / "derived",
            root / "validation",
            root / ".checkpoints",
        ):
            _secure_dir(path)

        raw_index: list[dict[str, Any]] = []
        index_path = root / "raw" / "index.jsonl"
        if index_path.exists():
            for line in index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    raw_index.append(item)
        return cls(root=root, state_root=state_root, raw_index=raw_index)

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
        _chmod_best_effort(body_path, 0o600)
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
        env_path.write_text(
            json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8"
        )
        _chmod_best_effort(env_path, 0o600)
        self.raw_index.append(envelope)
        index_path = self.root / "raw" / "index.jsonl"
        with index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(envelope, sort_keys=True) + "\n")
        _chmod_best_effort(index_path, 0o600)
        return raw_hash

    def state(self) -> dict[str, Any]:
        return _read_json_object(self.state_root / "state.json")

    def save_state(self, state: dict[str, Any]) -> None:
        _write_json_private(self.state_root / "state.json", state)

    def pseudonym(self, raw_id: str) -> str:
        state = self.state()
        salt_hex = state.get("pseudonym_salt")
        if not salt_hex:
            salt_hex = secrets.token_hex(32)
            state["pseudonym_salt"] = salt_hex
            self.save_state(state)
        digest = hmac.new(
            bytes.fromhex(str(salt_hex)), raw_id.encode(), hashlib.sha256
        ).hexdigest()
        return "dev-" + digest[:16]

    def resource_day_complete(self, resource_key: str, day: date) -> bool:
        state = self.state()
        completed = state.get("resource_days", {})
        if not isinstance(completed, dict):
            return False
        days = completed.get(resource_key, [])
        return day.isoformat() in days if isinstance(days, list) else False

    def mark_resource_day_complete(self, resource_key: str, day: date) -> None:
        state = self.state()
        completed = state.setdefault("resource_days", {})
        if not isinstance(completed, dict):
            completed = {}
            state["resource_days"] = completed
        days = completed.setdefault(resource_key, [])
        if not isinstance(days, list):
            days = []
            completed[resource_key] = days
        value = day.isoformat()
        if value not in days:
            days.append(value)
            days.sort()
            self.save_state(state)

    def _checkpoint_path(self, resource_key: str, day: date) -> Path:
        digest = hashlib.sha256(resource_key.encode("utf-8")).hexdigest()
        return self.root / ".checkpoints" / f"{digest}_{day.isoformat()}.json"

    def save_resource_day_checkpoint(
        self, resource_key: str, day: date, payload: dict[str, Any]
    ) -> None:
        path = self._checkpoint_path(resource_key, day)
        _write_json_private(
            path,
            {"resource": resource_key, "day": day.isoformat(), "payload": payload},
        )

    def load_resource_day_checkpoint(
        self, resource_key: str, day: date
    ) -> dict[str, Any] | None:
        path = self._checkpoint_path(resource_key, day)
        if not path.exists():
            return None
        value = _read_json_object(path)
        if value.get("resource") != resource_key or value.get("day") != day.isoformat():
            return None
        payload = value.get("payload")
        return payload if isinstance(payload, dict) else None

    def has_resource_day_checkpoint(self, resource_key: str, day: date) -> bool:
        return self.load_resource_day_checkpoint(resource_key, day) is not None

    def finish_active_run(self) -> None:
        state = self.state()
        state.pop("active_run_root", None)
        state["resource_days"] = {}
        self.save_state(state)
        shutil.rmtree(self.root / ".checkpoints", ignore_errors=True)

    def write_table(
        self, relative_stem: str, rows: list[dict[str, Any]]
    ) -> tuple[Path, Path]:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError(
                "pyarrow is required to create the mandated Parquet export"
            ) from exc

        csv_path = self.root / f"{relative_stem}.csv"
        pq_path = self.root / f"{relative_stem}.parquet"
        _secure_dir(csv_path.parent)
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
        _chmod_best_effort(csv_path, 0o600)
        _chmod_best_effort(pq_path, 0o600)
        return csv_path, pq_path

    def manifest(self, extra: dict[str, Any]) -> dict[str, Any]:
        files = []
        for path in sorted(self.root.rglob("*")):
            relative = path.relative_to(self.root)
            if ".checkpoints" in relative.parts:
                continue
            if (
                path.is_file()
                and path.name != "manifest.json"
                and not path.name.endswith(".zip")
            ):
                files.append(
                    {
                        "path": str(relative),
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
        manifest_path = self.root / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        _chmod_best_effort(manifest_path, 0o600)
        return manifest

    def secure_tree(self) -> None:
        _chmod_best_effort(self.root, 0o700)
        for path in self.root.rglob("*"):
            if path.is_dir():
                _chmod_best_effort(path, 0o700)
            elif path.is_file():
                _chmod_best_effort(path, 0o600)

    def package_zip(self) -> Path:
        self.secure_tree()
        zip_path = self.root.with_suffix(".zip")
        with zipfile.ZipFile(
            zip_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for path in sorted(self.root.rglob("*")):
                relative = path.relative_to(self.root)
                if ".checkpoints" in relative.parts:
                    continue
                if path.is_file():
                    archive.write(path, arcname=str(relative))
        _chmod_best_effort(zip_path, 0o600)
        return zip_path

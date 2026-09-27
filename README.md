# FusionSolar read-only exporter

A local, owner-authorised exporter for **read-only** Huawei FusionSolar web/frontend telemetry. It is not Huawei's official Northbound/OpenAPI interface and it contains no plant-control capability.

## Quick start

Install [uv](https://docs.astral.sh/uv/), then:

```bash
git clone https://github.com/WebshopCompany/fusionsolar-readonly-exporter.git
cd fusionsolar-readonly-exporter
uv sync --frozen
uv run fusionsolar-export
```

The CLI asks for the FusionSolar browser host before credentials. Copy the host from the signed-in FusionSolar browser URL, for example a `region...fusionsolar.huawei.com` or supported `uni...fusionsolar.huawei.com` host. No credentials are sent until the host has been validated as a Huawei FusionSolar hostname and a supported login route has been derived.

Then enter credentials locally:

```text
FusionSolar browser host:
FusionSolar username:
FusionSolar password: ********
```

The username is whatever FusionSolar accepts; it is **not assumed to be an email address**.

The first successful run probes the account's observed history and performs a backfill from the oldest observed boundary. Empty periods, API failures and a probable retention boundary remain distinct in the coverage report. Later runs re-fetch a deterministic overlap and resume incomplete per-resource/per-day work safely. Use `uv run fusionsolar-export --full` to deliberately rebuild from the oldest observed history.

If FusionSolar requires a CAPTCHA, the image is saved locally outside the export ZIP and the program asks you to type the code. The file is deleted after the attempt.

Read-only requests use bounded connection/read timeouts and bounded retries for transient connection failures, HTTP 429 and selected 5xx responses. Authentication POSTs are deliberately not automatically retried. If the authenticated session expires during a long backfill, the run stops rather than spraying requests; run the same command again, re-enter credentials locally, and the active export resumes from durable private checkpoints.

Output is written beneath a timestamped `output/` directory and includes raw JSON/JSONL, normalised CSV + Parquet, validation/coverage reports, manifest/hashes, and a ZIP package. Treat exports as private account telemetry. Runtime state is kept separately under `state/` and is not packaged. On POSIX systems the exporter applies private directory/file permissions on a best-effort basis.

See `docs/signal-semantics.md` before interpreting battery signals 30001/30002 or charge/discharge signs. Vendor-reported SOH/status values remain vendor telemetry, not validated battery-health ground truth. See `TROUBLESHOOTING.md` for sanitised diagnostic guidance.

## Supported Python

CI exercises Python 3.11, 3.12 and 3.13. The package declares `>=3.11,<3.14`.


## Independence and access terms

This independent utility is not affiliated with or endorsed by Huawei. Use it only with the account
owner's authorisation and subject to the terms that apply to the relevant FusionSolar service. The
owner-web interface is not a documented public API and may change without notice; technical read-only
enforcement is not a claim of contractual or legal compliance.

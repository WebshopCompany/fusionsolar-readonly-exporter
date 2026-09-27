# FusionSolar read-only exporter

A local, owner-authorised exporter for **read-only** Huawei FusionSolar web/frontend telemetry. It is not Huawei's official Northbound/OpenAPI interface and it contains no plant-control capability.

## Quick start

```bash
git clone https://github.com/WebshopCompany/fusionsolar-readonly-exporter.git
cd fusionsolar-readonly-exporter
poetry install
poetry run fusionsolar-export
```

Then enter credentials locally:

```text
FusionSolar username:
FusionSolar password: ********
```

The username is whatever FusionSolar accepts; it is **not assumed to be an email address**.

The first successful run probes the account's available history and performs a full backfill. Later runs use a safe overlap and deduplicate, which is suitable for periodic or monthly collection. Use `poetry run fusionsolar-export --full` to deliberately rebuild from the earliest available history.

If automatic host discovery cannot safely establish the data host, the program stops and asks for the FusionSolar host shown in the browser, for example `region01eu5.fusionsolar.huawei.com` or an equivalent `uni...` host. It does not spray credentials across guessed regions.

If FusionSolar requires a CAPTCHA, the image is saved locally outside the export ZIP and the program asks you to type the code. The file is deleted after the attempt.

Output is written beneath a timestamped `output/` directory and includes raw JSON/JSONL, normalised CSV + Parquet, validation reports, manifest/hashes, and a ZIP package. Treat exports as private account telemetry.

See `docs/signal-semantics.md` before interpreting battery signals 30001/30002 or charge/discharge signs. Vendor-reported SOH/status values remain vendor telemetry, not validated battery-health ground truth. See `TROUBLESHOOTING.md` for sanitised diagnostic guidance.

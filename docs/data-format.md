# Data format

A timestamped run directory contains:

- `raw/`: sanitised request/response envelopes and JSONL index. Raw Huawei response bodies are retained
  for owner custody; authentication exchanges are never captured.
- `normalised/telemetry.csv` and `.parquet`: long-format historical series.
- `normalised/daily_aggregates.csv` and `.parquet`: Huawei/vendor daily aggregate fields.
- `normalised/current_diagnostics.csv` and `.parquet`: latest/current-only device, module/pack, SOH,
  temperature, current, status, alarm and other exposed diagnostics.
- `derived/`: explicitly derived diagnostics only; no derived value silently replaces vendor data.
- `validation/`: gap/duplicate/range/monotonicity/sign/aggregate-discrepancy reports.
- `manifest.json`: file hashes, run metadata, source-interface classification and capability summary.
- final ZIP: everything above except private `state/` and CAPTCHA material.

Normalised telemetry records preserve `source_endpoint`, pseudonymous device, device class, Huawei
`signal_id`, Huawei/source label, source unit, raw value, UTC timestamp, Europe/London local timestamp,
raw-response hash and semantic status.

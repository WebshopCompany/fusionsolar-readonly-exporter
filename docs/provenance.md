# Software and data provenance

This utility acquires owner-authorised observational telemetry through Huawei FusionSolar's web/frontend interface. It is not Huawei Northbound/OpenAPI and it does not claim vendor support for the reverse-engineered interface.

Raw non-authentication response bytes are retained locally and hashed before normalisation. Normalised records carry source endpoint, source signal identifier, source label/unit when exposed, and a raw-response hash where available. Authentication payloads, credentials, cookies, headers, session values and CAPTCHA material are excluded from raw custody.

Public Git contains code, documentation and synthetic/redacted fixtures only. Real account exports, plant/device identifiers and session material must remain outside the repository.

Vendor-reported SOH, alarms, status, temperature and similar diagnostics remain vendor telemetry. The utility makes no calibrated-truth, SOH/RUL/degradation ground-truth, production-readiness, zero-loss, novelty or scientific-validation claim.

## Reproducible dependency baseline

The package pins `fusion-solar-py==0.1.2` and records the inspected upstream commit `3e02b9f5d831673070e0f7ddac7d9db53ca2368b`. Dependencies and development tools are resolved in `uv.lock`; `uv sync --frozen` treats that lockfile as the reproducibility source and fails if it is missing.

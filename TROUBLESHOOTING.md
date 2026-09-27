# Troubleshooting

Run the unmodified exporter first and keep diagnostics sanitised.

## Safe diagnostic sequence

1. Confirm the browser can sign in to the same FusionSolar owner account.
2. Re-run the CLI and enter the exact username accepted by FusionSolar; do not assume it is an email address.
3. If safe host discovery cannot validate the account region, pass `--host` using the FusionSolar hostname visible in the browser.
4. If a CAPTCHA is requested, solve the locally saved image. Do not upload the image, credentials or session material.
5. Re-run with the default request delay before changing rate settings.
6. Inspect only sanitised exception types, HTTP status classes, endpoint purposes and validation summaries.

## Data handling

Never paste or publish usernames, passwords, cookies, CSRF/session values, plant/device identifiers or real telemetry when asking for support. Export ZIPs are private account data.

## Read-only invariant

Do not add control, configuration, commissioning, firmware, charging-policy, export-limiting, start/stop or other state-changing endpoints. Any newly required read endpoint must be added to the exact allowlist with constrained request keys and tests proving denied paths remain denied.

## Semantics

Preserve original Huawei signal IDs, source labels/units, UTC timestamps and `Europe/London` station context. Do not silently reinterpret battery 30001/30002, flip endpoint-specific signs, or replace vendor aggregates with derived integration.

# Security and read-only boundary

This exporter is intentionally **read-only**. All network I/O is centralised in
`readonly_transport.py`, which denies every HTTP method/path/purpose tuple not present in its
explicit allowlist and validates permitted request keys before network I/O.

Never add Huawei control, configuration, commissioning, firmware, start/stop, export-limiting,
charging-policy, or device-setting endpoints. In particular,
`/rest/pvms/web/device/v1/deviceExt/set-config-signals` is forbidden.

Credentials are entered locally at runtime, kept only in process memory, never logged, never placed
in manifests, and never persisted by this project. Cookies/tokens are not persisted. Session expiry
fails closed and requires local re-authentication before the active run resumes. Export bundles contain
telemetry and identifiers and are private; `output/`, `state/`, `raw/`, `normalised/`,
`derived/`, and `validation/` are Git-ignored. On POSIX systems private runtime directories are
restricted to the local user and generated files/archives are written with private permissions on a
best-effort basis.

Report security concerns without attaching credentials, cookies, tokens, or real telemetry.

# Architecture

The exporter is a local CLI with five layers: credential prompt/authentication, strict read-only
transport, topology/capability discovery, sequential acquisition, and raw-first export/validation.

`readonly_transport.py` is the only project module permitted to import `requests` or perform HTTP
I/O. It validates the exact `(method, path, purpose)` tuple, allowed host suffix, query/body keys and
forbidden-path patterns before a request is sent. Some Huawei read/query/login calls use POST, so
"GET-only" is not a sufficient safety rule.

The pinned `fusion-solar-py==0.1.2` dependency supplies only its password-encryption helper and
published module-signal catalogue. The exporter deliberately does **not** instantiate or expose
`FusionSolarClient`, because that upstream class contains `active_power_control()` and a genuine
configuration write path. Inspected upstream commit: `3e02b9f5d831673070e0f7ddac7d9db53ca2368b`.

Each run discovers account topology afresh. Raw IDs may appear in the owner's private raw responses,
but normalised tables use a locally salted HMAC pseudonym. The salt and incremental watermark are
private runtime state and never enter the export ZIP.

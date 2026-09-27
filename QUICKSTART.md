# FusionSolar Stage-1 quick start

Stage-1 is the owner-side compatibility check for this read-only utility. It is intentionally narrower than the normal exporter.

## What Stage-1 does

Stage-1:

- validates the FusionSolar browser URL/hostname before credentials are sent;
- asks for the username locally and the password with hidden input;
- uses the existing authentication, CAPTCHA and session handling;
- discovers plants and devices;
- performs at most one read-only realtime request for one discovered device;
- prints sanitised PASS/FAIL diagnostics only;
- always reports `HISTORICAL_REQUESTS: 0` and `BACKFILL_STARTED: NO`.

Stage-1 does **not** run the historical exporter, probe history boundaries, backfill data, create an export ZIP, or write normalised/raw telemetry output.

## Prerequisites

- Python 3.11, 3.12 or 3.13.
- `uv` in the repository-declared range `>=0.12.18,<0.13`.
- The source folder. Git is useful if cloning the repository, but setup does not require Git once the source folder exists.
- The account owner must be able to sign in to FusionSolar and see the browser URL/hostname.

The setup scripts check the declared `uv` range and stop with explicit installation/upgrade instructions if `uv` is missing or too old/new. They do not run remote installer text automatically.

## macOS

From the repository folder:

```sh
./setup.sh
./run.sh
```

If `uv` is missing or outside the required range, the setup script points to the explicit Homebrew installation/upgrade command and the official `uv` documentation. Rerun `./setup.sh` afterwards.

## Linux

From the repository folder:

```sh
./setup.sh
./run.sh
```

If `uv` is missing or outside the required range, use your chosen trusted package method (for example `pipx` where available) or the official `uv` installation documentation, then rerun `./setup.sh`.

## Windows PowerShell

From the repository folder:

```powershell
.\setup.ps1
.\run.ps1
```

If `uv` is missing or outside the required range, the setup script prints an explicit `winget` command and the official `uv` documentation. Rerun `.\setup.ps1` afterwards.

## During the validation

Copy the browser URL or hostname from the signed-in owner's FusionSolar browser session when prompted. The host is validated before credential entry. The validator does not save the host, username, password, cookies, tokens, CAPTCHA content or telemetry.

If a CAPTCHA is required, the image exists only in the local private Stage-1 work directory for the authentication attempt and is deleted by the authentication handler.

## Safe diagnostics to share

The following Stage-1 output is designed to be safe to share for diagnosis:

- `STAGE1_VALIDATOR_VERSION`;
- `HOST_PATTERN_CLASS` and `HOST_VALIDATION`;
- `AUTHENTICATION` / `STAGE1_OPERATION`;
- `CAPTCHA_HANDLING_OCCURRED` and `SESSION_ESTABLISHED`;
- `PLANT_COUNT` and `DEVICE_COUNT`;
- `DEVICE_CLASSES` (coarse classes only);
- `REALTIME_READ`;
- `ERROR_CLASS` and `HTTP_STATUS_CLASS` when present;
- `HISTORICAL_REQUESTS: 0`;
- `BACKFILL_STARTED: NO`;
- `STAGE1_RESULT`.

Do **not** share the exact hostname, username/password, plant/device identifiers or serials, cookies/tokens/session values, CAPTCHA image/code, raw API responses or telemetry values.

## Full historical export is separate

The normal historical exporter is `fusionsolar-export`. Its first successful run can probe available history and backfill data, and it can create private raw/normalised/manifest/coverage output and a ZIP. That is deliberately **not** part of Stage-1.

Only run the full exporter when you intentionally want that separate behaviour and are authorised to acquire the account's historical telemetry.

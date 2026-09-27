#!/usr/bin/env sh
set -eu

UV_MIN='0.12.18'
UV_MAX='0.13'

fail() {
  printf '%s\n' "$1" >&2
  exit "${2:-1}"
}

OS_NAME="$(uname -s 2>/dev/null || printf unknown)"
case "$OS_NAME" in
  Darwin) PLATFORM='macOS' ;;
  Linux) PLATFORM='Linux' ;;
  *) fail 'This setup script supports macOS and Linux. On Windows use setup.ps1.' 2 ;;
esac
printf 'Platform: %s\n' "$PLATFORM"

PYTHON=''
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)' >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done
[ -n "$PYTHON" ] || fail 'Python 3.11, 3.12 or 3.13 is required. Install a supported Python and rerun setup.' 2
printf 'Python: %s\n' "$("$PYTHON" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"

if command -v git >/dev/null 2>&1; then
  printf 'Git: available\n'
else
  printf 'Git: not found (not required once the source folder has been obtained).\n'
fi

uv_in_range() {
  "$PYTHON" - "$1" <<'PY'
import sys
def parse(value):
    try:
        return tuple(int(part) for part in value.split('.'))
    except ValueError:
        raise SystemExit(1)
v = parse(sys.argv[1])
raise SystemExit(0 if parse('0.12.18') <= v < parse('0.13') else 1)
PY
}

uv_help() {
  if [ "$PLATFORM" = 'macOS' ]; then
    printf '%s\n' 'Install/upgrade uv with Homebrew: brew install uv  (or: brew upgrade uv)' >&2
  else
    printf '%s\n' "Install a uv version in the repository range ${UV_MIN} <= uv < ${UV_MAX}." >&2
    printf '%s\n' "If you use pipx: pipx install 'uv>=0.12.18,<0.13'" >&2
  fi
  printf '%s\n' 'Official installation guidance: https://docs.astral.sh/uv/getting-started/installation/' >&2
  printf '%s\n' 'This script does not execute remote installer text automatically.' >&2
}

if ! command -v uv >/dev/null 2>&1; then
  uv_help
  fail 'uv is required; install it explicitly, then rerun setup.' 2
fi
UV_VERSION="$(uv --version | awk '{print $2}')"
if ! uv_in_range "$UV_VERSION"; then
  printf 'Installed uv %s is outside required range >=0.12.18,<0.13.\n' "$UV_VERSION" >&2
  uv_help
  fail 'Upgrade/downgrade uv into the declared repository range, then rerun setup.' 2
fi
printf 'uv: %s (supported)\n' "$UV_VERSION"

uv sync --frozen --python "$PYTHON"
uv run --frozen fusionsolar-stage1 --help >/dev/null

printf '%s\n' 'Setup complete.'
printf '%s\n' 'Next command: ./run.sh'

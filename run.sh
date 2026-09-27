#!/usr/bin/env sh
set -eu
exec uv run --frozen fusionsolar-stage1 "$@"

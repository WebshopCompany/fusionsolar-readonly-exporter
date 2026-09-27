$ErrorActionPreference = 'Stop'
& uv run --frozen fusionsolar-stage1 @args
exit $LASTEXITCODE

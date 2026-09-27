from pathlib import Path
import tomllib


ROOT = Path(__file__).parents[1]


def test_setup_wrappers_enforce_declared_uv_range_and_frozen_sync():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["uv"]["required-version"] == ">=0.12.18,<0.13"
    for name in ("setup.sh", "setup.ps1"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "0.12.18" in text and "0.13" in text
        assert "sync --frozen" in text
        assert "fusionsolar-stage1 --help" in text


def test_setup_does_not_execute_unreviewed_remote_shell_text():
    combined = "\n".join(
        (ROOT / name).read_text(encoding="utf-8") for name in ("setup.sh", "setup.ps1")
    ).lower()
    assert "curl | sh" not in combined
    assert "curl -" not in combined
    assert "invoke-expression" not in combined


def test_run_wrappers_launch_only_stage1():
    for name in ("run.sh", "run.ps1"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "fusionsolar-stage1" in text
        assert "fusionsolar-export" not in text
        assert "--full" not in text


def test_quickstart_separates_stage1_from_historical_export():
    text = (ROOT / "QUICKSTART.md").read_text(encoding="utf-8")
    assert "HISTORICAL_REQUESTS: 0" in text
    assert "BACKFILL_STARTED: NO" in text
    assert "Full historical export is separate" in text
    assert "Windows PowerShell" in text and "macOS" in text and "Linux" in text


def test_ci_exercises_all_three_desktop_families():
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for required in (
        "ubuntu-latest",
        "macos-latest",
        "windows-latest",
        "./setup.sh",
        ".\\setup.ps1",
    ):
        assert required in text

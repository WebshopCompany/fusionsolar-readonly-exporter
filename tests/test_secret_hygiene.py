from pathlib import Path


def _private_markers() -> tuple[str, ...]:
    return (
        "owner-example" + "@invalid",
        "real-password-" + "value",
        "eyJ-example-" + "token",
        "dp-session=" + "example-private-value",
    )


def test_public_tree_contains_no_private_fixture_markers():
    root = Path(__file__).parents[1]
    markers = _private_markers()
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix == ".pyc":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        assert not any(marker in text for marker in markers), path

from pathlib import Path


def _terms() -> tuple[str, ...]:
    return (
        "Ste" + "phen",
        "neigh" + "bour",
        "Ge" + "za",
        "CIRCU" + "BATT",
        "PH" + "D-",
        "Research" + " OS",
        "Share" + "Point",
        "University of " + "Essex",
    )


def test_repository_contains_no_internal_context_terms():
    root = Path(__file__).parents[1]
    terms = tuple(term.lower() for term in _terms())
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix == ".pyc":
            continue
        try:
            content = path.read_text(encoding="utf-8").lower()
        except (UnicodeDecodeError, OSError):
            continue
        assert not any(term in content for term in terms), path

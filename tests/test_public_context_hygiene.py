from pathlib import Path

from fusionsolar_readonly_exporter.hygiene import find_terms, iter_controlled_text_files


def _terms() -> tuple[str, ...]:
    return (
        "Ste" + "phen",
        "neigh" + "bour",
        "Ge" + "za",
        "CIRCU" + "BATT",
        "PH" + "D-GOV",
        "PH" + "D-AST",
        "PH" + "D-DEC",
        "Research" + " OS",
        "Share" + "Point",
        "University of " + "Essex",
    )


def test_repository_contains_no_internal_context_terms():
    root = Path(__file__).parents[1]
    assert find_terms(root, _terms()) == []


def test_generated_venv_build_cache_and_runtime_paths_are_not_scanned(tmp_path):
    term = _terms()[0]
    generated = [
        tmp_path / ".venv/lib/python3.13/site-packages/packaging/ranges.py",
        tmp_path / "build/generated.txt",
        tmp_path / "dist/generated.txt",
        tmp_path / ".pytest_cache/generated.txt",
        tmp_path / "package.egg-info/PKG-INFO",
        tmp_path / "output/export.txt",
        tmp_path / "state/state.json",
    ]
    for path in generated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(term, encoding="utf-8")
    (tmp_path / "README.md").write_text("public utility", encoding="utf-8")
    assert find_terms(tmp_path, _terms()) == []
    assert [path.relative_to(tmp_path) for path in iter_controlled_text_files(tmp_path)] == [
        Path("README.md")
    ]


def test_controlled_source_match_is_detected(tmp_path):
    term = _terms()[1]
    path = tmp_path / "docs/context.md"
    path.parent.mkdir(parents=True)
    path.write_text(term, encoding="utf-8")
    hits = find_terms(tmp_path, _terms())
    assert hits == [(Path("docs/context.md"), term.lower())]

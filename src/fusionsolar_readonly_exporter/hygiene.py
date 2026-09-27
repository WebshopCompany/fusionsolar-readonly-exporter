from __future__ import annotations

from pathlib import Path
from typing import Iterable

_CONTROLLED_ROOT_FILES = frozenset(
    {
        ".gitignore",
        "LICENSE",
        "README.md",
        "QUICKSTART.md",
        "setup.sh",
        "setup.ps1",
        "run.sh",
        "run.ps1",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        "TROUBLESHOOTING.md",
        "pyproject.toml",
        "uv.lock",
    }
)
_CONTROLLED_DIRS = (".github", "docs", "examples", "src", "tests")
_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".venv",
        ".stage1-private",
        "build",
        "dist",
        "output",
        "state",
        "raw",
        "normalised",
        "derived",
        "validation",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".pyright",
    }
)
_TEXT_SUFFIXES = frozenset(
    {".py", ".md", ".toml", ".yml", ".yaml", ".json", ".jsonl", ".txt", ".csv", ".lock", ".sh", ".ps1"}
)


def _generated_metadata(path: Path) -> bool:
    return any(part.endswith((".egg-info", ".dist-info")) for part in path.parts)


def iter_controlled_text_files(root: Path) -> Iterable[Path]:
    """Yield only repository-controlled public text surfaces."""
    for name in sorted(_CONTROLLED_ROOT_FILES):
        path = root / name
        if path.is_file():
            yield path
    for dirname in _CONTROLLED_DIRS:
        base = root / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part in _EXCLUDED_PARTS for part in path.parts) or _generated_metadata(path):
                continue
            if path.suffix.lower() in _TEXT_SUFFIXES or path.name in _CONTROLLED_ROOT_FILES:
                yield path


def find_terms(root: Path, terms: Iterable[str]) -> list[tuple[Path, str]]:
    wanted = tuple(term.lower() for term in terms)
    hits: list[tuple[Path, str]] = []
    for path in iter_controlled_text_files(root):
        try:
            content = path.read_text(encoding="utf-8").lower()
        except (UnicodeDecodeError, OSError):
            continue
        for term in wanted:
            if term in content:
                hits.append((path.relative_to(root), term))
    return hits

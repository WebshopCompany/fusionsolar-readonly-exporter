import re
from pathlib import Path

from fusionsolar_readonly_exporter.hygiene import iter_controlled_text_files


def _patterns() -> tuple[re.Pattern[str], ...]:
    pieces = (
        r"AK" + r"IA[0-9A-Z]{16}",
        r"gh" + r"[pousr]_[A-Za-z0-9_]{20,}",
        r"-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"Bearer" + r"\s+[A-Za-z0-9._~+/=-]{20,}",
    )
    return tuple(re.compile(piece, re.IGNORECASE) for piece in pieces)


def test_controlled_public_tree_has_no_common_secret_shapes():
    root = Path(__file__).parents[1]
    hits = []
    for path in iter_controlled_text_files(root):
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in _patterns():
            if pattern.search(content):
                hits.append((path.relative_to(root), pattern.pattern))
    assert hits == []

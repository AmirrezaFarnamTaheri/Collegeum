"""Guards the one architectural rule that makes the core testable offline.

Everything under ``predoc_pipeline.core`` must import only the standard
library (``fuzzy.py``'s optional ``rapidfuzz`` accelerator is the sole,
explicitly-guarded exception: it is wrapped in a try/except and the module
provides a complete stdlib fallback). If this test starts failing, something
in core started depending on a package that is not guaranteed to be installed,
which quietly breaks the "runs anywhere with just python3" property the rest
of the test suite relies on.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parents[2] / "src" / "predoc_pipeline" / "core"

# rapidfuzz is imported defensively inside a try/except with a full fallback
# implementation; it is the one permitted "soft" dependency in this package.
ALLOWED_THIRD_PARTY = {"rapidfuzz"}

_STDLIB = set(sys.stdlib_module_names) | {"__future__"}


def _top_level(module: str) -> str:
    return module.split(".", 1)[0]


def _imports_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(_top_level(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import within the package
            if node.module:
                modules.add(_top_level(node.module))
    return modules


class TestCoreHasNoThirdPartyImports(unittest.TestCase):
    def test_core_package_is_stdlib_only(self):
        self.assertTrue(CORE_DIR.is_dir(), f"expected {CORE_DIR} to exist")
        offenders: dict[str, set[str]] = {}
        for path in sorted(CORE_DIR.glob("*.py")):
            found = _imports_in(path) - _STDLIB - ALLOWED_THIRD_PARTY
            if found:
                offenders[path.name] = found
        self.assertFalse(
            offenders,
            f"core/ must be stdlib-only (plus guarded rapidfuzz); found: {offenders}",
        )

    def test_rapidfuzz_import_is_exception_guarded(self):
        source = (CORE_DIR / "fuzzy.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        guarded = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                imported = set()
                for stmt in node.body:
                    if isinstance(stmt, ast.ImportFrom) and stmt.module:
                        imported.add(_top_level(stmt.module))
                    elif isinstance(stmt, ast.Import):
                        for alias in stmt.names:
                            imported.add(_top_level(alias.name))
                if "rapidfuzz" in imported:
                    guarded = True
        self.assertTrue(guarded, "rapidfuzz import in fuzzy.py must be inside a try/except")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)

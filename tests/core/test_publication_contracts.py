"""Enforce actual committed-publication integrity before CI approves changes."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "audit_publications.py"


def _load():
    spec = importlib.util.spec_from_file_location("audit_publications", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicationContractTests(unittest.TestCase):
    def test_real_snapshot_has_no_structural_errors(self):
        audit = _load()
        summary, findings = audit.audit(ROOT)
        self.assertGreater(summary["state"], 0)
        self.assertGreater(summary["dashboard"], 0)
        self.assertGreater(summary["rss"], 0)
        self.assertFalse([item for item in findings if item["severity"] == "error"])

    def test_strict_cli_is_stdlib_only(self):
        child = subprocess.run(
            [sys.executable, "-S", str(SCRIPT), "--strict"],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)

    def test_broken_public_count_is_detected(self):
        audit = _load()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in audit.REQUIRED:
                dst = root / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes((ROOT / name).read_bytes())
            dest = root / "docs/data/listings.json"
            data = json.loads(dest.read_text(encoding="utf-8"))
            data["count"] = -99
            dest.write_text(json.dumps(data), encoding="utf-8")
            _, findings = audit.audit(root)
            self.assertIn("count-mismatch", {x["code"] for x in findings})

    def test_unlisted_rss_url_is_detected(self):
        audit = _load()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in audit.REQUIRED:
                dst = root / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes((ROOT / name).read_bytes())
            dest = root / "docs/feed.xml"
            text = dest.read_text(encoding="utf-8")
            self.assertIn("<item>", text)
            first_item, rest = text.split("<item>", 1)
            first, tail = rest.split("</item>", 1)
            start = first.index("<link>") + len("<link>")
            end = first.index("</link>", start)
            first = first[:start] + "https://example.invalid/not-listed" + first[end:]
            dest.write_text(first_item + "<item>" + first + "</item>" + tail,
                            encoding="utf-8")
            _, findings = audit.audit(root)
            self.assertIn("rss-link-absent-public", {x["code"] for x in findings})


if __name__ == "__main__":
    unittest.main()

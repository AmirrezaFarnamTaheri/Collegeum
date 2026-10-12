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


    def test_site_links_and_rss_stylesheet_have_correct_destination(self):
        page = (ROOT / "docs/index.html").read_text(encoding="utf-8")
        style = (ROOT / "docs/rss.xsl").read_text(encoding="utf-8")
        self.assertNotIn("amirrezafarnamtaheri/predoc-not-org", page)
        self.assertIn("github.com/AmirrezaFarnamTaheri/Collegeum", page)
        self.assertIn("atom:link[@rel='self']/@href", style)
        self.assertNotIn('select="/rss/channel/link"/>/feed.xml', style)

    def test_materializer_contains_all_static_dashboard_assets(self):
        tool = (ROOT / "tools/build_single_file.py").read_text(encoding="utf-8")
        for pattern in ('"docs/*.html"', '"docs/*.svg"', '"docs/*.xsl"', '"docs/*.png"'):
            self.assertIn(pattern, tool)


    def test_rss_title_and_category_divergence_is_detected(self):
        audit = _load()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in audit.REQUIRED:
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((ROOT / name).read_bytes())
            file = root / "docs/feed.xml"
            text = file.read_text(encoding="utf-8")
            self.assertIn("<item>\n<title>", text)
            text = text.replace("<item>\n<title>", "<item>\n<title>Incorrect: ", 1)
            text = text.replace("</category>", " INSPECT</category>", 1)
            file.write_text(text, encoding="utf-8")
            _, findings = audit.audit(root)
            codes = {item["code"] for item in findings}
            self.assertIn("rss-title-divergence", codes)
            self.assertIn("rss-category-divergence", codes)

    def test_invalid_javascript_json_constants_are_rejected(self):
        audit = _load()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in audit.REQUIRED:
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((ROOT / name).read_bytes())
            dest = root / "docs/data/listings.json"
            data = json.loads(dest.read_text(encoding="utf-8"))
            data["count"] = float("nan")
            dest.write_text(json.dumps(data), encoding="utf-8")
            _, findings = audit.audit(root)
            self.assertIn("unreadable-file", {item["code"] for item in findings})


    def test_complete_json_quality_report_can_be_archived(self):
        with TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "outputs" / "publication-audit.json"
            result = subprocess.run(
                [sys.executable, "-S", str(SCRIPT), "--strict",
                 "--json-report", str(artifact)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(artifact.read_text(encoding="utf-8"))
            self.assertGreater(data["summary"]["dashboard"], 0)
            self.assertIsInstance(data["findings"], list)
            self.assertEqual(
                data["counts"].get("error", 0),
                sum(f["severity"] == "error" for f in data["findings"]),
            )

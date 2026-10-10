"""Distribution hashes must survive Git's Windows/Linux newline conversion."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import build_single_file


class DistributionTests(unittest.TestCase):
    def test_text_line_endings_have_identical_manifests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'source.py'
            with patch.object(build_single_file, 'REPO_ROOT', root):
                path.write_bytes(b'first\r\nsecond\r\n')
                windows = build_single_file.build_manifest([path])
                path.write_bytes(b'first\nsecond\n')
                linux = build_single_file.build_manifest([path])
            self.assertEqual(windows, linux)

    def test_binary_fixtures_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'fixture.pdf'
            content = b'%PDF\r\n\xff\x00\r\n'
            path.write_bytes(content)
            with patch.object(build_single_file, 'REPO_ROOT', root):
                payload, _ = build_single_file.build_manifest([path])
            self.assertEqual(payload['fixture.pdf'], content)

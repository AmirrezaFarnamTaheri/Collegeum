"""Verify distribution freshness and materialization using only the standard library."""

from __future__ import annotations

import runpy
import subprocess
import sys
import tempfile
from pathlib import Path

from build_single_file import OUTPUT_PATH, build_manifest, collect_files


def main() -> None:
    expected, digest = build_manifest(collect_files())
    artifact = runpy.run_path(str(OUTPUT_PATH))
    actual = artifact['_unpack']()
    artifact['_verify'](actual)
    if actual != expected or artifact['MANIFEST_SHA256'] != digest:
        raise SystemExit('Distribution is stale; run python tools/build_single_file.py')
    with tempfile.TemporaryDirectory(prefix='predoc-distribution-') as temporary:
        target = Path(temporary) / 'project'
        subprocess.run([sys.executable, '-S', str(OUTPUT_PATH), str(target)], check=True)
        for name, content in expected.items():
            if (target / name).read_bytes() != content:
                raise SystemExit(f'Materialization mismatch: {name}')
    print(f'Distribution verified: {len(expected)} files, manifest {digest}')


if __name__ == '__main__':
    main()

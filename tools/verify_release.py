"""Inspect local release archives without extracting or installing them."""

from __future__ import annotations

import hashlib
import json
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = {'.env', '.codegraph', '.serena', '.statamcp', '__pycache__', '.venv', 'feedback.json'}


def check_names(names: list[str]) -> None:
    for name in names:
        path = Path(name)
        if FORBIDDEN & set(path.parts) or path.suffix in {'.db', '.sqlite3', '.pyc'}:
            raise SystemExit(f'Local state or credentials included in release: {name}')


def main() -> None:
    directory = ROOT / 'build' / 'release'
    wheels = sorted(directory.glob('*.whl'))
    sources = sorted(directory.glob('*.tar.gz'))
    if len(wheels) != 1 or len(sources) != 1:
        raise SystemExit('Expected one wheel and one source archive in build/release')
    with zipfile.ZipFile(wheels[0]) as wheel:
        check_names(wheel.namelist())
        for path in (ROOT / 'src' / 'predoc_pipeline').rglob('*'):
            if path.is_file() and (path.suffix == '.py' or path.name == 'py.typed'):
                name = path.relative_to(ROOT / 'src').as_posix()
                if wheel.read(name) != path.read_bytes():
                    raise SystemExit(f'Wheel source mismatch: {name}')
    with tarfile.open(sources[0], 'r:gz') as archive:
        names = archive.getnames()
        check_names(names)
        prefix = names[0].split('/')[0]
        for name in ('FINALIZATION.md', 'uv.lock', 'compile_project.py',
                     'tools/verify_single_file.py', 'tools/verify_release.py'):
            file = archive.extractfile(f'{prefix}/{name}')
            if file is None or file.read() != (ROOT / name).read_bytes():
                raise SystemExit(f'Source archive mismatch: {name}')
    records = [{'file': path.name, 'bytes': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
               for path in [*wheels, *sources]]
    (directory / 'verification.json').write_text(
        json.dumps({'verified': True, 'artifacts': records}, indent=2) + '\n', encoding='utf-8',
    )
    print(json.dumps(records, indent=2))


if __name__ == '__main__':
    main()

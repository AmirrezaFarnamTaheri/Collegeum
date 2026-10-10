"""Shared registry identity checks before any collector starts."""

import os
import re
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_ENV_NAME = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def read_registry(path: str | Path) -> dict[str, Any]:
    file = Path(path)
    if not file.exists():
        return {}
    with file.open('rb') as handle:
        raw = tomllib.load(handle)
    names: set[str] = set()
    for kind in ('board', 'feed', 'portal'):
        entries = raw.get(kind, [])
        if not isinstance(entries, list):
            raise ValueError(f'{kind} sources must be an array of tables')
        for index, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                raise ValueError(f'{kind} source {index} must be a table')
            name = entry.get('name')
            if not isinstance(name, str) or not name.strip() or name != name.strip():
                raise ValueError(f'{kind} source {index} requires a nonblank, trimmed name')
            name = _ENV_NAME.sub(lambda match: os.environ.get(
                match.group(1), match.group(2) or ''), name)
            if not name.strip() or name != name.strip():
                raise ValueError(
                    f'{kind} source {index} requires a nonblank, trimmed resolved name')
            entry['name'] = name
            if name in names:
                raise ValueError(f'duplicate source name: {name}')
            names.add(name)
            if not isinstance(entry.get('enabled', True), bool):
                raise ValueError(f'source {name}: enabled must be a boolean')
            if kind in ('feed', 'portal'):
                url = entry.get('url')
                try:
                    parsed = urlsplit(url) if isinstance(url, str) else None
                    valid_url = (isinstance(url, str) and parsed is not None
                                 and parsed.scheme in ('http', 'https')
                                 and bool(parsed.hostname) and url == url.strip()
                                 and not any(char.isspace() for char in url))
                    if parsed is not None:
                        _ = parsed.port  # Validate an explicitly configured port too.
                except ValueError:
                    valid_url = False
                if not valid_url:
                    raise ValueError(f'source {name}: url must be an absolute HTTP(S) URL')
                for flag in ('verified', 'follow_links'):
                    if not isinstance(entry.get(flag, False), bool):
                        raise ValueError(f'source {name}: {flag} must be a boolean')
                limit = entry.get('max_items')
                if limit is not None and (type(limit) is not int or limit < 1):
                    raise ValueError(f'source {name}: max_items must be a positive integer')
                tags = entry.get('tags', [])
                if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
                    raise ValueError(f'source {name}: tags must be an array of strings')
    return raw

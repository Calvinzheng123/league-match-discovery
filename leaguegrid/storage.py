"""Atomic local output and a deliberately small .env reader."""
import json
import os
import tempfile
from pathlib import Path


def load_env(path):
    """Read KEY=value literals. Do not execute shell syntax or expand variables."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise ValueError('Each .env entry must use KEY=value.')
        name, value = line.split('=', 1)
        name, value = name.strip(), value.strip()
        if not name.isidentifier():
            raise ValueError('Invalid environment variable name in .env.')
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(name, value)


def save_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         delete=False) as output:
            temporary = output.name
            json.dump(document, output, indent=2, ensure_ascii=False)
            output.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)

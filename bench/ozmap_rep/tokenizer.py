"""The o200k_base token counter of the sign-off 5 reasoning predicate (tiktoken 0.14.0, pinned vocabulary file).

Standard library only on the caller's side: when tiktoken 0.14.0 is importable here it is used in process, otherwise
the counts come from the pinned interpreter (config.TOKENIZER_PYTHON, the repository .venv the pilot froze) in one
child process. Before counting, the cached vocabulary file must hash to the pinned value, so tiktoken never fetches
anything. Any failure gives None per text, which the predicate reports as "reasoning inclusion not shown"; a count is
never guessed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from . import config

_CHILD = r'''
import json, sys
import tiktoken
enc = tiktoken.get_encoding("o200k_base")
texts = json.loads(sys.stdin.read())
print(json.dumps({"version": tiktoken.__version__, "counts": [len(enc.encode(t)) for t in texts]}))
'''


def cache_dir():
    return Path(os.environ.get('TIKTOKEN_CACHE_DIR') or os.environ.get('DATA_GYM_CACHE_DIR')
                or Path(tempfile.gettempdir()) / 'data-gym-cache')


def vocabulary_ok():
    d = cache_dir()
    for name, digest in config.TOKENIZER['cache_files'].items():
        p = d / name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            return False
    return True


def _in_process(texts):
    try:
        import tiktoken
    except ImportError:
        return None
    if getattr(tiktoken, '__version__', None) != config.TOKENIZER['tiktoken']:
        return None
    enc = tiktoken.get_encoding(config.TOKENIZER['encoding'])
    return [len(enc.encode(t)) for t in texts]


def _child(texts):
    exe = Path(config.TOKENIZER_PYTHON)
    if not exe.is_file():
        return None
    env = {k: v for k, v in os.environ.items()
           if k.upper() in ('SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'TEMP', 'TMP', 'PATH', 'TIKTOKEN_CACHE_DIR',
                            'DATA_GYM_CACHE_DIR')}
    try:
        done = subprocess.run([str(exe), '-I', '-c', _CHILD], input=json.dumps(texts), capture_output=True, text=True,
                              encoding='utf-8', timeout=120, env=env)
        out = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or out.get('version') != config.TOKENIZER['tiktoken']:
        return None
    counts = out.get('counts')
    return counts if isinstance(counts, list) and len(counts) == len(texts) else None


def count(texts):
    """[token count or None] for each text."""
    texts = list(texts)
    if not texts:
        return []
    if any(not isinstance(t, str) for t in texts) or not vocabulary_ok():
        return [None] * len(texts)
    got = _in_process(texts)
    if got is None:
        got = _child(texts)
    return got if got is not None else [None] * len(texts)


def record():
    return {'tiktoken': config.TOKENIZER['tiktoken'], 'encoding': config.TOKENIZER['encoding'],
            'vocabulary_ok': vocabulary_ok(), 'interpreter': str(config.TOKENIZER_PYTHON)}

"""Atomic file IO helpers shared by every phase."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_bytes_atomic(path: Path, data: bytes, *, overwrite: bool = True) -> None:
    """Write via a temp file + rename so a crash never leaves a half file.

    With overwrite=False an existing file is never replaced (raises FileExistsError).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and path.exists():
        raise FileExistsError(str(path))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if not overwrite:
            # link() fails if the target appeared meanwhile; no silent clobber.
            os.link(tmp, path)
            os.unlink(tmp)
        else:
            os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_text_atomic(path: Path, text: str, *, overwrite: bool = True) -> None:
    write_bytes_atomic(path, text.encode("utf-8"), overwrite=overwrite)


def write_json(path: Path, obj: Any, *, overwrite: bool = True) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    write_text_atomic(path, text, overwrite=overwrite)


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def append_jsonl(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[Any]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out

"""JSON checkpoints, prefix verification and crash-safe OS writer locking."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import uuid


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


@contextmanager
def writer_lock(folder):
    handle = (Path(folder) / ".run.lock").open("a+b")
    locked = False
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise RuntimeError("Another writer is using this run directory") from e
        locked = True
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def verified_prefix(path, size, expected_hash):
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError("Invalid checkpoint offset")
    path = Path(path)
    if path.stat().st_size < size:
        raise ValueError("Dataset is shorter than its committed checkpoint")
    digest = hashlib.sha256()
    remaining = size
    with path.open("rb") as f:
        while remaining:
            block = f.read(min(1_048_576, remaining))
            if not block:
                raise ValueError("Truncated checkpoint prefix")
            digest.update(block)
            remaining -= len(block)
        if size:
            f.seek(size - 1)
            if f.read(1) != b"\n":
                raise ValueError("Checkpoint is not at a complete record boundary")
    if digest.hexdigest() != expected_hash:
        raise ValueError("Dataset prefix does not match checkpoint checksum")
    return digest


def preserve_uncommitted_tail(path, size):
    path = Path(path)
    if path.stat().st_size == size:
        return None
    backup = path.parent / ("uncommitted-tail-" + uuid.uuid4().hex + ".jsonl")
    with path.open("rb") as src, backup.open("xb") as dest:
        src.seek(size)
        while block := src.read(1_048_576):
            dest.write(block)
        dest.flush()
        os.fsync(dest.fileno())
    with path.open("r+b") as f:
        f.truncate(size)
    return backup.name

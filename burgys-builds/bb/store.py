"""On-disk storage: atomic writes, cross-platform locking, disk guard.

Everything the controller remembers lives under one data root so that a
restart can rebuild its world from disk (master brief, section 21) and so
that retention has a single place to prune (section 22).

The lock is a directory, because ``mkdir`` is atomic on NTFS and on POSIX
alike; ``msvcrt``/``fcntl`` would have needed two code paths.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from .errors import DiskFull, StorageError, ValidationError

#: Refuse to start work that would leave less than this much room.
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
#: Warn (but continue) below this.
WARN_FREE_BYTES = 10 * 1024 * 1024 * 1024  # 10 GiB


class Paths:
    """The data layout from section 22 of the brief."""

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root).resolve()
        self.projects = self.root / "projects"
        self.builds = self.root / "builds"
        self.artifacts = self.root / "artifacts"
        self.logs = self.root / "logs"
        self.cache = self.root / "cache"
        self.ota = self.root / "ota"

    def ensure(self) -> "Paths":
        for p in (self.root, self.projects, self.builds, self.artifacts,
                  self.logs, self.cache, self.ota):
            p.mkdir(parents=True, exist_ok=True)
        return self

    def build_dir(self, build_id: str) -> Path:
        from .ids import validate_build_id

        return self.builds / validate_build_id(build_id)

    def artifact_dir(self, build_id: str) -> Path:
        from .ids import validate_build_id

        return self.artifacts / validate_build_id(build_id)

    def log_file(self, build_id: str) -> Path:
        from .ids import validate_build_id

        return self.logs / (validate_build_id(build_id) + ".log")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Paths({self.root!s})"


# --------------------------------------------------------------------------
# atomic json
# --------------------------------------------------------------------------

def read_json(path: str | os.PathLike, default: Any = None) -> Any:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    if not text.strip():
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageError(f"{p} is not valid JSON: {exc}") from exc


def write_json(path: str | os.PathLike, data: Any) -> Path:
    """Write JSON atomically: temp file in the same directory, then replace.

    ``os.replace`` is atomic on Windows and POSIX, which is what makes a
    half-written state file impossible after a crash or a power cut.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_with_retry(tmp, p)
    except OSError as exc:
        _unlink(tmp)
        if exc.errno in (errno.ENOSPC, errno.EDQUOT):
            raise DiskFull(f"no space left writing {p}") from exc
        raise StorageError(f"cannot write {p}: {exc}") from exc
    except BaseException:
        _unlink(tmp)
        raise
    return p


#: Windows refuses to replace a file another process currently has open, and
#: virus scanners and indexers open freshly written files routinely.  The
#: replacement is still atomic; it just occasionally has to wait a moment.
REPLACE_ATTEMPTS = 5
REPLACE_BACKOFF = 0.1


def _replace_with_retry(src: str | os.PathLike, dst: str | os.PathLike) -> None:
    transient = {errno.EACCES, errno.EPERM, getattr(errno, "EBUSY", None)}
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            last = attempt == REPLACE_ATTEMPTS - 1
            if last or exc.errno not in transient:
                raise
            time.sleep(REPLACE_BACKOFF * (2 ** attempt))


def _unlink(path: str | os.PathLike) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


# --------------------------------------------------------------------------
# locking
# --------------------------------------------------------------------------

#: One lock object per path per process, so threads queue up in memory
#: before they start creating and removing directories on disk.
_THREAD_LOCKS: dict = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = _THREAD_LOCKS[key] = threading.Lock()
        return lock


class FileLock:
    """Advisory lock backed by an atomically created directory.

    ``mkdir`` is the atomic primitive on NTFS and POSIX alike, so it works
    across processes as well as threads.  A lock whose owner has been gone
    longer than ``stale_after`` is broken, so a killed controller does not
    wedge the queue for ever.

    The staleness check uses the lock directory's own mtime whenever the
    owner file is not readable yet: ``mkdir`` stamps the mtime immediately,
    while the owner file appears a moment later, and treating that gap as
    "stale" would let a second waiter tear down a lock that is very much
    alive.
    """

    def __init__(self, path: str | os.PathLike, timeout: float = 10.0,
                 stale_after: float = 300.0, poll: float = 0.05) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self.stale_after = stale_after
        self.poll = poll
        self._held = False
        self._thread_lock = _thread_lock(self.path)
        self._thread_held = False

    def _owner_file(self) -> Path:
        return self.path / "owner.json"

    def acquire(self) -> "FileLock":
        deadline = time.monotonic() + self.timeout
        if not self._thread_lock.acquire(timeout=max(0.0, self.timeout)):
            raise StorageError(f"timed out waiting for lock {self.path}")
        self._thread_held = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            while True:
                try:
                    self.path.mkdir()
                except FileExistsError:
                    if self._break_if_stale():
                        continue
                    if time.monotonic() >= deadline:
                        raise StorageError(f"timed out waiting for lock {self.path}")
                    time.sleep(self.poll)
                    continue
                try:
                    write_json(self._owner_file(),
                               {"pid": os.getpid(), "at": time.time()})
                except (StorageError, OSError):
                    # Someone broke the lock underneath us, or the disk is
                    # full.  Either way we do not hold it.
                    shutil.rmtree(self.path, ignore_errors=True)
                    raise
                self._held = True
                return self
        except BaseException:
            self._release_thread()
            raise

    def _break_if_stale(self) -> bool:
        info = read_json(self._owner_file(), default=None)
        if isinstance(info, dict) and info.get("at"):
            created = float(info["at"])
        else:
            try:
                created = self.path.stat().st_mtime
            except OSError:
                return True      # it vanished; try to take it
        if time.time() - created < self.stale_after:
            return False
        shutil.rmtree(self.path, ignore_errors=True)
        return True

    def _release_thread(self) -> None:
        if self._thread_held:
            self._thread_held = False
            self._thread_lock.release()

    def release(self) -> None:
        if self._held:
            shutil.rmtree(self.path, ignore_errors=True)
            self._held = False
        self._release_thread()

    def __enter__(self) -> "FileLock":
        return self.acquire()

    def __exit__(self, *exc: Any) -> None:
        self.release()


# --------------------------------------------------------------------------
# disk
# --------------------------------------------------------------------------

def disk_free(path: str | os.PathLike) -> int:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(str(p)).free


def disk_status(path: str | os.PathLike, min_free: int = MIN_FREE_BYTES,
                warn_free: int = WARN_FREE_BYTES) -> dict:
    free = disk_free(path)
    if free < min_free:
        level = "CRITICAL"
    elif free < warn_free:
        level = "WARN"
    else:
        level = "OK"
    return {"free_bytes": free, "free_gb": round(free / 2 ** 30, 2), "level": level}


def require_disk(path: str | os.PathLike, min_free: int = MIN_FREE_BYTES) -> None:
    free = disk_free(path)
    if free < min_free:
        raise DiskFull(
            f"only {free / 2 ** 30:.2f} GB free at {path}, "
            f"{min_free / 2 ** 30:.2f} GB required"
        )


# --------------------------------------------------------------------------
# hashing and retention
# --------------------------------------------------------------------------

def sha256_file(path: str | os.PathLike, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def iter_json(directory: str | os.PathLike, pattern: str = "*.json") -> Iterator[Any]:
    for path in sorted(Path(directory).glob(pattern)):
        data = read_json(path)
        if data is not None:
            yield data


def safe_child(root: str | os.PathLike, *parts: str) -> Path:
    """Join ``parts`` under ``root`` and refuse to escape it.

    Path traversal guard for every agent-supplied name (brief, section 20).
    """
    root_p = Path(root).resolve()
    for part in parts:
        if not part or part in (".", "..") or "\x00" in part:
            raise ValidationError(f"unusable path component {part!r}")
        if os.path.isabs(part) or "\\" in part or "/" in part:
            raise ValidationError(f"path component must be a plain name: {part!r}")
    target = root_p.joinpath(*parts).resolve()
    if target != root_p and root_p not in target.parents:
        raise ValidationError(f"path escapes {root_p}: {target}")
    return target

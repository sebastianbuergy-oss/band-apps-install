"""The little bit of git we need, always as an argument list.

Never ``shell=True`` and never a string built from caller input - that is
the command-injection guard from section 20, enforced by construction.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import ValidationError
from .ids import validate_commit

TIMEOUT = 60


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    for a in args:
        if not isinstance(a, str):
            raise ValidationError(f"git argument must be a string: {a!r}")
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=TIMEOUT, check=False,
    )


def is_repo(repo: Path) -> bool:
    return _git(repo, "rev-parse", "--git-dir").returncode == 0


def head_commit(repo: Path) -> str:
    res = _git(repo, "rev-parse", "HEAD")
    if res.returncode != 0:
        raise ValidationError(f"cannot read HEAD in {repo}: {res.stderr.strip()}")
    return validate_commit(res.stdout.strip())


def current_branch(repo: Path) -> str:
    res = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return res.stdout.strip() if res.returncode == 0 else ""


def is_clean(repo: Path) -> tuple[bool, list]:
    res = _git(repo, "status", "--porcelain")
    if res.returncode != 0:
        return False, [res.stderr.strip()]
    dirty = [ln for ln in res.stdout.splitlines() if ln.strip()]
    return (not dirty), dirty


def commit_exists(repo: Path, commit: str) -> bool:
    validate_commit(commit)
    return _git(repo, "cat-file", "-e", commit + "^{commit}").returncode == 0


def commit_subject(repo: Path, commit: str) -> str:
    validate_commit(commit)
    res = _git(repo, "log", "-1", "--format=%s", commit)
    return res.stdout.strip() if res.returncode == 0 else ""


def remote_url(repo: Path) -> str:
    res = _git(repo, "remote", "get-url", "origin")
    return res.stdout.strip() if res.returncode == 0 else ""


def behind_remote(repo: Path, branch: str) -> int | None:
    """How many commits ``origin/branch`` is ahead of us.  ``None`` if unknown.

    Used by the Claude/Codex conflict guard (section 17): never work on a
    stand we know to be stale.
    """
    res = _git(repo, "rev-list", "--count", f"HEAD..origin/{branch}")
    if res.returncode != 0:
        return None
    try:
        return int(res.stdout.strip())
    except ValueError:
        return None

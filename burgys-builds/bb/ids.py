"""Build identifiers: ``BB-YYYYMMDD-CODE-NNN`` (master brief, section 14)."""
from __future__ import annotations

import datetime as _dt
import re

from .errors import ValidationError

BUILD_ID_RE = re.compile(r"^BB-(\d{8})-([A-Z0-9]{2,6})-(\d{3,})$")
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}[a-z0-9]$")
PROJECT_CODE_RE = re.compile(r"^[A-Z0-9]{2,6}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,98}$")


def derive_code(name: str) -> str:
    """Derive a short project code: initials of the words, else the first
    letters.  ``GoSafeHome`` -> ``GSH``, ``thy-gnosis`` -> ``TG``.
    """
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w]
    if len(words) >= 2:
        code = "".join(w[0] for w in words)
    elif words:
        # CamelCase gets split on the capitals, otherwise take the first three.
        parts = re.findall(r"[A-Z][a-z0-9]*", words[0]) or [words[0]]
        code = "".join(p[0] for p in parts) if len(parts) >= 2 else words[0][:3]
    else:
        raise ValidationError(f"cannot derive a project code from {name!r}")
    code = re.sub(r"[^A-Za-z0-9]", "", code).upper()[:6]
    if not PROJECT_CODE_RE.match(code):
        raise ValidationError(f"derived code {code!r} is not usable for {name!r}")
    return code


def make_build_id(code: str, sequence: int, day: _dt.date | None = None) -> str:
    validate_project_code(code)
    if sequence < 1:
        raise ValidationError("build sequence starts at 1")
    day = day or _dt.datetime.now().date()
    return f"BB-{day:%Y%m%d}-{code}-{sequence:03d}"


def parse_build_id(build_id: str) -> tuple[_dt.date, str, int]:
    m = BUILD_ID_RE.match(build_id or "")
    if not m:
        raise ValidationError(f"not a build id: {build_id!r}")
    return _dt.datetime.strptime(m.group(1), "%Y%m%d").date(), m.group(2), int(m.group(3))


def validate_build_id(build_id: str) -> str:
    parse_build_id(build_id)
    return build_id


def validate_project_id(project_id: str) -> str:
    if not PROJECT_ID_RE.match(project_id or ""):
        raise ValidationError(f"not a project id: {project_id!r}")
    return project_id


def validate_project_code(code: str) -> str:
    if not PROJECT_CODE_RE.match(code or ""):
        raise ValidationError(f"not a project code: {code!r}")
    return code


def validate_commit(commit: str) -> str:
    if not COMMIT_RE.match((commit or "").lower()):
        raise ValidationError(f"not a git commit sha: {commit!r}")
    return commit.lower()


def validate_branch(branch: str) -> str:
    if not BRANCH_RE.match(branch or "") or ".." in branch:
        raise ValidationError(f"not a usable branch name: {branch!r}")
    return branch

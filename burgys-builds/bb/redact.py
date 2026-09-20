"""Secret redaction.

Rule 9 and rule 20 of the master brief: secrets never reach a log, a status
file, a manifest or an agent handoff.  We do not try to be clever - we
redact by *key name* for structured data and by *pattern* for free text,
and we default to redacting when unsure.
"""
from __future__ import annotations

import re
from typing import Any

MASK = "[REDACTED]"

# Key names whose value is never printed, matched case-insensitively as a
# substring so that ASC_KEY_ID, cm_api_token and privateKeyPem all match.
SECRET_KEY_HINTS = (
    "secret", "token", "password", "passwd", "passphrase", "apikey", "api_key",
    "private_key", "privatekey", "p12", "keystore", "certificate_password",
    "cert_password", "auth", "credential", "session", "cookie", "signature",
    "issuer_id", "key_id", "app_store_connect", "asc_key", "keychain",
)

# Key names that merely *sound* secret but are safe and useful to see.
SECRET_KEY_ALLOW = (
    "auth_mode", "auth_required", "token_required", "authorized",
)

_PATTERNS = (
    # PEM blocks (any type) - collapse the whole block.
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    # JSON-ish or env-ish "key": "value" / KEY=value assignments.
    re.compile(
        r"(?i)\b([A-Za-z0-9_.\-]*(?:secret|token|password|passphrase|api[_-]?key|private[_-]?key|credential)[A-Za-z0-9_.\-]*)"
        r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
    ),
    # Apple App Store Connect / GitHub style opaque tokens.
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}\b"),
    # Anything base64-ish and long enough to be key material.
    re.compile(r"\b[A-Za-z0-9+/]{60,}={0,2}\b"),
)


def _is_secret_key(key: str) -> bool:
    low = str(key).lower()
    if low in SECRET_KEY_ALLOW:
        return False
    return any(hint in low for hint in SECRET_KEY_HINTS)


def redact_text(text: str) -> str:
    """Redact secrets in a free-text blob (build logs, tracebacks, stderr)."""
    if not text:
        return text
    out = text
    for pat in _PATTERNS:
        if pat.groups >= 3:
            out = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", out)
        else:
            out = pat.sub(MASK, out)
    return out


def redact(value: Any) -> Any:
    """Redact a JSON-shaped structure, by key name and by value pattern."""
    if isinstance(value, dict):
        return {
            k: (MASK if _is_secret_key(k) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value

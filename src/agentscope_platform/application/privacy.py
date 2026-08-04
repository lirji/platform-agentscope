"""Deterministic redaction for data crossing public streaming boundaries."""

import re
from collections.abc import Mapping, Sequence
from typing import Any

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_CN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_CN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")


def redact_pii(value: Any) -> Any:
    """Return a JSON-compatible copy with common PII patterns masked."""
    if isinstance(value, str):
        redacted = _ID_CN.sub("[REDACTED-id-card]", value)
        redacted = _EMAIL.sub("[REDACTED-email]", redacted)
        return _PHONE_CN.sub("[REDACTED-phone]", redacted)
    if isinstance(value, Mapping):
        return {key: redact_pii(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_pii(item) for item in value]
    return value

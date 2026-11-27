"""Small helpers for cleaning untrusted text before it is stored or logged."""

from __future__ import annotations

import re

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def strip_control(value: str) -> str:
    """Replace control characters (including newlines) so log lines cannot be forged."""
    return _CONTROL_CHARS.sub(" ", value).strip()


def clip(value: str | None, max_length: int) -> str | None:
    """Clean and truncate optional text to a column's maximum length."""
    if value is None:
        return None
    return strip_control(value)[:max_length]
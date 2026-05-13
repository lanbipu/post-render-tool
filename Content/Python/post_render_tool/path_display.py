"""Path display helpers for compact UI labels."""

from __future__ import annotations


def format_middle_ellipsis_path(path: str, *, max_chars: int = 64) -> str:
    """Return a path label with the middle collapsed to an ellipsis."""
    text = str(path or "")
    if len(text) <= max_chars:
        return text

    separator = _dominant_separator(text)
    if separator:
        compact = _format_path_by_segments(text, separator)
        if compact and len(compact) <= max_chars:
            return compact

    return _format_middle_ellipsis_text(text, max_chars=max_chars)


def _dominant_separator(text: str) -> str:
    slash_count = text.count("/")
    backslash_count = text.count("\\")
    if slash_count == 0 and backslash_count == 0:
        return ""
    return "\\" if backslash_count > slash_count else "/"


def _format_path_by_segments(text: str, separator: str) -> str:
    parts = [part for part in text.split(separator) if part]
    if len(parts) < 3:
        return ""

    prefix = _path_prefix(text, separator, parts)
    if not prefix:
        return ""
    return f"{prefix}{separator}...{separator}{parts[-1]}"


def _path_prefix(text: str, separator: str, parts: list[str]) -> str:
    if len(parts[0]) == 2 and parts[0][1] == ":":
        if len(parts) < 3:
            return ""
        return separator.join(parts[:2])
    if text.startswith(separator):
        return separator + parts[0]
    return parts[0]


def _format_middle_ellipsis_text(text: str, *, max_chars: int) -> str:
    if max_chars <= 3:
        return "." * max(0, max_chars)

    keep = max_chars - 3
    left = max(1, keep // 2)
    right = max(1, keep - left)
    return f"{text[:left]}...{text[-right:]}"

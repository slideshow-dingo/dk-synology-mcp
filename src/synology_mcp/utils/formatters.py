"""Shared formatting and response utilities."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class ResponseFormat(str, Enum):
    """Output format for tool responses."""
    MARKDOWN = "markdown"
    JSON = "json"


def format_size(size_bytes: int | float) -> str:
    """Format bytes into human-readable size."""
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}" if i > 0 else f"{int(size)} B"


def format_timestamp(ts: int | float | str | None) -> str:
    """Format a Unix timestamp or ISO string to human-readable."""
    if ts is None:
        return "N/A"
    try:
        if isinstance(ts, str):
            return ts
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return str(ts)


def format_response(data: Any, fmt: ResponseFormat = ResponseFormat.MARKDOWN) -> str:
    """Format response data as JSON or markdown."""
    if fmt == ResponseFormat.JSON:
        return json.dumps(data, indent=2, default=str)
    if isinstance(data, str):
        return data
    return json.dumps(data, indent=2, default=str)


def success_response(message: str, data: Any = None) -> str:
    """Build a standard success response."""
    result = {"status": "success", "message": message}
    if data is not None:
        result["data"] = data
    return json.dumps(result, indent=2, default=str)


def error_response(message: str, suggestion: Optional[str] = None) -> str:
    """Build a standard error response with optional suggestion."""
    result = {"status": "error", "message": message}
    if suggestion:
        result["suggestion"] = suggestion
    return json.dumps(result, indent=2, default=str)


def exception_message(e: Exception) -> str:
    """Extract the most useful human-readable message from an exception."""
    for attr in ("error_message", "message", "msg"):
        value = getattr(e, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()

    error_str = str(e).strip()
    if error_str:
        return error_str

    if getattr(e, "args", ()):
        parts = [str(arg).strip() for arg in e.args if str(arg).strip()]
        if parts:
            return "; ".join(parts)

    cause = getattr(e, "__cause__", None) or getattr(e, "__context__", None)
    if isinstance(cause, Exception) and cause is not e:
        cause_message = exception_message(cause)
        if cause_message:
            return cause_message

    return e.__class__.__name__


def handle_synology_error(e: Exception, operation: str) -> str:
    """Consistent error handling for Synology API errors."""
    error_str = exception_message(e)

    # Common Synology error patterns
    if "119" in error_str or "timeout" in error_str.lower():
        return error_response(
            f"{operation} failed: Session timeout",
            "The NAS session expired. Try the operation again — it will reconnect automatically."
        )
    if "403" in error_str or "permission" in error_str.lower():
        return error_response(
            f"{operation} failed: Permission denied",
            "Check that the configured user has the required permissions for this operation."
        )
    if "404" in error_str or "not found" in error_str.lower():
        return error_response(
            f"{operation} failed: Resource not found",
            "Verify the path or resource ID is correct."
        )
    if (
        "connection" in error_str.lower()
        or "refused" in error_str.lower()
        or "cannot reach nas" in error_str.lower()
    ):
        return error_response(
            f"{operation} failed: Cannot reach NAS",
            "Check that the NAS is online and the host/port configuration is correct."
        )

    if "requested method does not exist" in error_str.lower():
        return error_response(
            f"{operation} failed: API method unavailable",
            "The Synology DSM version does not support this API method. Check your DSM version compatibility."
        )

    return error_response(f"{operation} failed: {error_str}")


def paginate_list(items: list, offset: int = 0, limit: int = 50) -> dict:
    """Apply pagination to a list of items."""
    total = len(items)
    page = items[offset : offset + limit]
    return {
        "total": total,
        "count": len(page),
        "offset": offset,
        "items": page,
        "has_more": total > offset + limit,
        "next_offset": offset + limit if total > offset + limit else None,
    }

"""Prompt sanitization for coordinator task requests."""

import re
from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException


ALLOWED_TASK_TYPES = {"code", "documentation", "qa", "style"}
MAX_PROMPT_LENGTH = 4096

_SECRET_PATTERNS = (
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN.*PRIVATE KEY-----", re.IGNORECASE | re.DOTALL),
    re.compile(r"password\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*[=:]\s*\S+", re.IGNORECASE),
)

_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\[\w .()\-\\]+"),
    re.compile(r"/(?:[\w .()\-]+/)+[\w .()\-]*"),
)

_MODEL_OVERRIDE_PATTERN = re.compile(r"(^|\n)\s*model\s*:\s*\S+.*?(?=\n|$)", re.IGNORECASE)


def _setting_value(settings: Any, name: str, default: Any) -> Any:
    if settings is None:
        return default
    return getattr(settings, name, default)


def _allowed_task_types(settings: Any) -> set[str]:
    configured = _setting_value(settings, "ALLOWED_TASK_TYPES", ALLOWED_TASK_TYPES)
    if isinstance(configured, str):
        return {item.strip() for item in configured.split(",") if item.strip()}
    if isinstance(configured, Iterable):
        return {str(item) for item in configured}
    return set(ALLOWED_TASK_TYPES)


async def sanitize_prompt(prompt: str, task_type: str, settings: Any | None = None) -> str:
    """Validate and normalize a prompt before assigning it to volunteers."""

    allowed_task_types = _allowed_task_types(settings)
    if task_type not in allowed_task_types:
        raise HTTPException(status_code=400, detail=f"Task type {task_type} not allowed")

    for pattern in _SECRET_PATTERNS:
        if pattern.search(prompt):
            raise HTTPException(status_code=400, detail="Secret detected")

    for pattern in _PATH_PATTERNS:
        if pattern.search(prompt):
            raise HTTPException(status_code=400, detail="File path detected")

    if _MODEL_OVERRIDE_PATTERN.search(prompt):
        raise HTTPException(status_code=400, detail="Model override detected")

    max_length = int(_setting_value(settings, "MAX_PROMPT_LENGTH", MAX_PROMPT_LENGTH))
    return prompt.strip()[:max_length]

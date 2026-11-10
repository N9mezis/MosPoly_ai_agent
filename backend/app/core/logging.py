"""Логирование без персональных данных и секретов (НФ-12, Ф-17)."""

from __future__ import annotations

import logging
import re

_SECRET_PATTERNS = (
    re.compile(r"(Authorization:\s*(?:Basic|Bearer)\s+)[A-Za-z0-9._\-+/=]+", re.IGNORECASE),
    re.compile(r"((?:credentials|api_key|password|token)\"?\s*[:=]\s*\"?)[^\s\",]+", re.IGNORECASE),
)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in _SECRET_PATTERNS:
            message = pattern.sub(r"\1***", message)
        record.msg = message
        record.args = ()
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # httpx пишет URL и заголовки на DEBUG; держим на WARNING.
    logging.getLogger("httpx").setLevel(logging.WARNING)

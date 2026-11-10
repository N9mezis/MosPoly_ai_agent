"""Сбор метаданных вызовов модели (без текстов промптов и ответов) для таблицы llm_calls.

Конвейер открывает `CallLog` на время проверки; клиенты LLM/эмбеддингов вызывают
`record_call`, и записи попадают в лог текущей проверки через contextvar.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field


@dataclass(slots=True)
class CallRecord:
    purpose: str
    provider: str
    model: str
    attempt: int
    latency_ms: int | None
    http_status: int | None
    outcome: str
    error_message: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    used_json_schema: bool = False
    chunk_key: str | None = None


@dataclass(slots=True)
class CallLog:
    records: list[CallRecord] = field(default_factory=list)


_current: contextvars.ContextVar[CallLog | None] = contextvars.ContextVar(
    "llm_call_log", default=None
)
_current_chunk: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm_chunk", default=None
)


def start_call_log() -> tuple[CallLog, contextvars.Token]:
    log = CallLog()
    return log, _current.set(log)


def stop_call_log(token: contextvars.Token) -> None:
    _current.reset(token)


def set_current_chunk(chunk_key: str | None) -> contextvars.Token:
    return _current_chunk.set(chunk_key)


def record_call(
    purpose: str,
    provider: str,
    model: str,
    attempt: int,
    latency_ms: int | None,
    http_status: int | None,
    outcome: str,
    error_message: str = "",
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    used_json_schema: bool = False,
) -> None:
    log = _current.get()
    if log is None:
        return
    log.records.append(
        CallRecord(
            purpose=purpose,
            provider=provider,
            model=model,
            attempt=attempt,
            latency_ms=latency_ms,
            http_status=http_status,
            outcome=outcome,
            error_message=error_message[:500],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            used_json_schema=used_json_schema,
            chunk_key=_current_chunk.get(),
        )
    )

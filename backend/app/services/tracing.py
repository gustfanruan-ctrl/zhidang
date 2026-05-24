"""Unified structured instrumentation for pipeline performance analysis.

Usage:
    from .tracing import new_trace, emit

    # Entry: set trace_id once
    new_trace("ext")  # or "rvw" for review pipeline

    # Anywhere downstream (zero arg change):
    emit("llm_first_token", segment_index=2, ttft_ms=3200)

Uses contextvars for implicit trace_id propagation — no function signature changes.
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid

logger = logging.getLogger("zhidang.metrics")

_trace_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id", default=None
)


def new_trace(prefix: str = "req") -> str:
    tid = f"{prefix}_{uuid.uuid4().hex[:12]}"
    _trace_var.set(tid)
    return tid


def current_trace() -> str | None:
    return _trace_var.get()


def emit(event: str, **fields) -> None:
    payload = {
        "_metric": event,
        "trace_id": _trace_var.get(),
        "ts": time.time(),
        **fields,
    }
    logger.info(json.dumps(payload, default=str))


def emit_llm(
    *,
    event: str = "llm_done",
    segment_index: int = -1,
    model: str = "",
    attempt_no: int = 1,
    input_tokens: int = 0,
    output_tokens: int = 0,
    ttft_ms: float = 0,
    total_ms: float = 0,
    tps: float = 0,
    status: str = "",
    error_type: str = "",
    error_msg: str = "",
    will_retry: bool = False,
    total_attempts: int = 1,
    final_status: str = "",
    degraded: bool = False,
):
    """Emit a structured LLM call event. All kwargs are optional — only non-zero/truthy fields are emitted."""
    f: dict = {"segment_index": segment_index, "model": model}
    if attempt_no > 0:
        f["attempt_no"] = attempt_no
    if input_tokens:
        f["input_tokens"] = input_tokens
    if output_tokens:
        f["output_tokens"] = output_tokens
    if ttft_ms:
        f["ttft_ms"] = round(ttft_ms, 1)
    if total_ms:
        f["total_ms"] = round(total_ms, 1)
    if tps:
        f["tps"] = round(tps, 1)
    if status:
        f["status"] = status
    if error_type:
        f["error_type"] = error_type
        f["error_msg"] = error_msg[:200]
        f["will_retry"] = will_retry
    if total_attempts > 1:
        f["total_attempts"] = total_attempts
    if final_status:
        f["final_status"] = final_status
    if degraded:
        f["degraded"] = True
    emit(event, **f)

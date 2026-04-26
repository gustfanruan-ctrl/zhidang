from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_progress(
    transcript_id: str | None = None,
    error: str | None = None,
    mode: str = "fallback",
    input_type: str = "text",
    current_turn: int = 0,
    max_turns: int = 8,
    extraction_status: str = "pending",
    comparison_status: str = "pending",
    llm_lines: list[str] | None = None,
) -> dict[str, Any]:
    extraction_step_status = "pending"
    if extraction_status in {"processing", "running"}:
        extraction_step_status = "running"
    elif extraction_status in {"completed", "success", "fallback"}:
        extraction_step_status = "completed"

    comparison_step_status = "pending"
    if comparison_status in {"processing", "running"}:
        comparison_step_status = "running"
    elif comparison_status in {"completed", "success", "fallback"}:
        comparison_step_status = "completed"

    return {
        "transcript_id": transcript_id,
        "steps": [
            {"name": "解析文件", "status": "completed"},
            {"name": "识别预期与场景", "status": extraction_step_status, "started_at": datetime.now(timezone.utc).isoformat()},
            {"name": "比对已有档案", "status": comparison_step_status},
            {"name": "规则校验", "status": "completed" if comparison_step_status == "completed" else "pending"},
        ],
        "current_step": 2 if extraction_step_status == "running" else (3 if comparison_step_status == "running" else 4 if comparison_step_status == "completed" else 1),
        "error": error,
        "mode": mode,
        "input_type": input_type,
        "current_turn": current_turn,
        "max_turns": max_turns,
        "extraction_status": extraction_status,
        "comparison_status": comparison_status,
        "llm_lines": llm_lines or [],
    }

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ReviewAction(BaseModel):
    transcript_id: str
    card_id: str
    action: Literal["approve", "reject"]
    reason: str | None = None


class OperationTypeCalibrationRequest(BaseModel):
    operation_type: Literal["create", "update", "skip"]


class OperationExecuteRequest(BaseModel):
    transcript_id: str
    card_ids: list[str] = Field(default_factory=list)
    field_updates: dict[str, dict[str, str]] = Field(default_factory=dict, description="card_id -> {field_name: new_value}")
    company_id: str | None = None
    card_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict, description="card_id -> card-level override fields")


class OperationExecuteResult(BaseModel):
    card_id: str
    execute_status: Literal["pending", "success", "failed", "skipped"]
    error: str | None = None

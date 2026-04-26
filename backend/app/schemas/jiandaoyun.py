from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CustomerSummary(BaseModel):
    _id: str | None = None
    comname_01: str | None = None
    com_type: str | None = None
    revenue_level: str | None = None
    if_access: str | None = None
    follow_form: str | None = None
    extra: dict[str, Any] | None = None


class YuqiRecord(BaseModel):
    _id: str | None = None
    com_name_ref: str | None = None
    yuqi_status: str | None = None
    detail_brief: str | None = None
    detail: str | None = None
    progress_subform: list[dict[str, Any]] | None = None
    raw: dict[str, Any] | None = None


class ChangjingRecord(BaseModel):
    _id: str | None = None
    title: str | None = None
    solve_what_ques: str | None = None
    solve_what_ans: str | None = None
    raw: dict[str, Any] | None = None


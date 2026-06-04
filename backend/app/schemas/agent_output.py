from __future__ import annotations

import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ValidationError, field_validator


class ExtractedFact(BaseModel):
    field_name: str
    value: str
    confidence: float
    source_quote: str
    source_type: Literal["text", "image"]
    category: Literal[
        "company_info",
        "contact_person",
        "requirements",
        "feedback",
        "renewal_intent",
        "competitor_mention",
        "action_items",
        "risk_signals",
    ] = "company_info"
    target_form: str | None = None

    @field_validator("field_name", "value")
    @classmethod
    def non_empty(cls, val: str) -> str:
        value = val.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, val: float) -> float:
        if not 0.0 <= val <= 1.0:
            raise ValueError(f"置信度必须在 0-1 之间，当前值: {val}")
        return round(val, 3)

    @field_validator("source_quote")
    @classmethod
    def quote_not_empty(cls, val: str) -> str:
        quote = val.strip()
        if len(quote) < 5:
            raise ValueError("来源引用不能为空或过短（至少 5 个字符）")
        return quote


class RecordChangeItem(BaseModel):
    field_name: str
    widget_name: str | None = None
    old_value: str | None = None
    new_value: str
    safety_status: str | None = None
    safety_reason: str | None = None

    @field_validator("field_name", "new_value")
    @classmethod
    def non_empty(cls, val: str) -> str:
        value = val.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value


class OperationCard(BaseModel):
    card_id: str = ""
    field_name: str | None = None
    operation_type: Literal["update", "create", "append_subform"]
    widget_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    confidence: float
    source_quote: str
    target_form: str | None = None
    safety_status: str | None = None
    safety_reason: str | None = None
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    execute_status: Literal["pending", "success", "failed", "skipped"] = "pending"
    change_items: list[RecordChangeItem] = []
    # 写入时需要的关联字段
    customer_id: str | None = None
    lookup_widget: str | None = None
    data_id: str | None = None
    customer_com_id: str | None = None
    customer_com_name: str | None = None
    # 场景表关联预期：related_yuqi_id 是简道云记录 id；
    # related_yuqi_card_id 是本次审核队列中预期卡片的 card_id，执行时会解析成记录 id。
    related_yuqi_id: str | None = None
    related_yuqi_card_id: str | None = None
    related_yuqi_source: str | None = None
    related_yuqi_summary: str | None = None
    related_yuqi_reason: str | None = None
    related_yuqi_confidence: float | None = None

    @field_validator("field_name")
    @classmethod
    def normalize_field_name(cls, val: str | None) -> str | None:
        if val is None:
            return None
        value = val.strip()
        return value or None

    @field_validator("new_value")
    @classmethod
    def normalize_new_value(cls, val: str | None) -> str | None:
        if val is None:
            return None
        value = val.strip()
        return value or None

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, val: float) -> float:
        if not 0.0 <= val <= 1.0:
            raise ValueError(f"置信度必须在 0-1 之间，当前值: {val}")
        return round(val, 3)

    @field_validator("source_quote")
    @classmethod
    def quote_not_empty(cls, val: str) -> str:
        quote = val.strip()
        if len(quote) < 5:
            raise ValueError("来源引用不能为空或过短（至少 5 个字符）")
        return quote

    @field_validator("old_value")
    @classmethod
    def old_value_check(cls, val: str | None, info):
        if info.data.get("operation_type") == "create" and val is not None:
            raise ValueError("create 操作的 old_value 应为 None")
        return val

    @field_validator("card_id")
    @classmethod
    def ensure_card_id(cls, val: str) -> str:
        return val.strip() or str(uuid4())

    @field_validator("change_items")
    @classmethod
    def ensure_change_items(cls, val: list[RecordChangeItem], info) -> list[RecordChangeItem]:
        if val:
            return val
        field_name = info.data.get("field_name")
        new_value = info.data.get("new_value")
        if field_name and new_value:
            return [RecordChangeItem(field_name=field_name, widget_name=info.data.get("widget_name"), old_value=info.data.get("old_value"), new_value=new_value)]
        raise ValueError("operation card 至少需要一个 change_item")


class AgentExtractionResult(BaseModel):
    facts: list[ExtractedFact]
    total_extracted: int

    @field_validator("facts")
    @classmethod
    def ensure_facts(cls, val: list[ExtractedFact]) -> list[ExtractedFact]:
        if len(val) == 0:
            raise ValueError("提取结果不能为空")
        return val


class AgentComparisonResult(BaseModel):
    operation_cards: list[OperationCard]
    total: int

    @field_validator("total")
    @classmethod
    def total_matches(cls, val: int, info) -> int:
        cards = info.data.get("operation_cards", [])
        if val != len(cards):
            raise ValueError(f"total ({val}) 与实际卡片数 ({len(cards)}) 不一致")
        return val


def _normalize_card_operation(raw_card: dict[str, Any]) -> dict[str, Any]:
    card = dict(raw_card or {})
    raw_operation = str(card.get("operation_type") or card.get("operation") or card.get("type") or "").strip()
    normalized = re.sub(r"[\s_\-:/（）()\[\]【】,，.!！？?]+", "", raw_operation.lower())

    if not card.get("target_form"):
        if any(token in normalized for token in ["expectation", "yuqi", "预期"]):
            card["target_form"] = "预期表"
        elif any(token in normalized for token in ["scenario", "changjing", "场景"]):
            card["target_form"] = "场景表"

    if any(token in normalized for token in ["append", "subform", "追加", "子表"]):
        card["operation_type"] = "append_subform"
    elif any(token in normalized for token in ["update", "modify", "edit", "change", "更新", "修改"]):
        card["operation_type"] = "update"
    elif any(token in normalized for token in ["create", "new", "add", "新增", "新建", "创建"]):
        card["operation_type"] = "create"
    return card


def validate_extraction_output(data: dict) -> dict:
    raw_facts = list((data or {}).get("facts") or [])
    validated_facts: list[ExtractedFact] = []
    validation_warnings: list[str] = []

    for idx, raw_fact in enumerate(raw_facts):
        fact: dict[str, Any] = dict(raw_fact or {})
        try:
            validated_facts.append(ExtractedFact.model_validate(fact))
            continue
        except ValidationError as exc:
            validation_warnings.append(f"fact[{idx}] 校验失败: {exc}")

        repaired_fact = dict(fact)
        repaired_fact.setdefault("source_type", "text")
        repaired_fact.setdefault("confidence", 0.5)
        repaired_fact.setdefault("category", "requirements")
        try:
            validated_facts.append(ExtractedFact.model_validate(repaired_fact))
        except ValidationError as exc:
            validation_warnings.append(f"fact[{idx}] 修复后仍失败: {exc}")

    result = AgentExtractionResult.model_validate(
        {
            "facts": [item.model_dump() for item in validated_facts],
            "total_extracted": len(validated_facts),
        }
    )
    payload = result.model_dump()
    if validation_warnings:
        payload["validation_warnings"] = validation_warnings
    return payload


def validate_comparison_output(data: dict) -> dict:
    payload = dict(data or {})
    payload["operation_cards"] = [
        _normalize_card_operation(card)
        for card in list(payload.get("operation_cards") or [])
        if isinstance(card, dict)
    ]
    payload["total"] = len(payload["operation_cards"])
    result = AgentComparisonResult.model_validate(payload)
    return result.model_dump()

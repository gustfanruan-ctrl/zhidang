"""
target_form 兜底推断规则
当 LLM 未填写 target_form 时，根据 field_name 自动补全。
"""
from __future__ import annotations
from typing import Any

# field_name → target_form 映射表
FIELD_TO_FORM: dict[str, str] = {
    # 预期表字段
    "detail_brief": "预期表",
    "detail": "预期表",
    "yuqi_status": "预期表",
    "promote_idea": "预期表",
    # 场景表字段
    "title": "场景表",
    "solve_what_ques": "场景表",
    "solve_what_ans": "场景表",
    # 客户主表字段
    "comname_01": "客户主表",
    "com_type": "客户主表",
    "revenue_level": "客户主表",
    "if_access": "客户主表",
    "follow_form": "客户主表",
}


def patch_target_form(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    遍历 facts，对 target_form 为 None/空字符串的条目，
    根据 field_name 自动补全。
    """
    patched = 0
    for fact in facts:
        current = fact.get("target_form")
        if current and str(current).strip():
            continue  # 已有值，跳过
        field_name = str(fact.get("field_name", "")).strip()
        inferred = FIELD_TO_FORM.get(field_name, "未知")
        fact["target_form"] = inferred
        patched += 1
    if patched:
        import logging
        logging.getLogger("zhidang").info(
            "target_form 兜底补全: %d 条事实被自动填充", patched
        )
    return facts

from __future__ import annotations

from uuid import uuid4
from typing import Any, Awaitable, Callable
import re
from difflib import SequenceMatcher

from .customer_matcher import match_customer
from .field_safety import check_operation_cards
from .jiandaoyun_client import JiandaoyunClient, JiandaoyunClientError

ToolExecutor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _normalize_key(value: str) -> str:
    text = (value or "").strip().lower()
    return re.sub(r"[\s_\-:/（）()【】\[\]，,。.!！？?]+", "", text)


FIELD_ALIASES: dict[str, dict[str, str]] = {
    "预期表": {
        "detailbrief": "预期简述",
        "预期简述": "预期简述",
        "预期摘要": "预期简述",
        "预期核心": "预期简述",
        "预期详情": "预期详情",
        "预期描述": "预期详情",
        "detail": "预期详情",
        "预期状态": "预期状态",
        "yuqistatus": "预期状态",
        "推进想法": "推进想法",
        "推进思路": "推进想法",
        "promoteidea": "推进想法",
    },
    "场景表": {
        "场景标题": "场景标题",
        "title": "场景标题",
        "业务场景": "场景标题",
        "场景": "场景标题",
        "解决什么问题": "解决什么问题",
        "业务诉求": "解决什么问题",
        "痛点分析": "解决什么问题",
        "solvewhatques": "解决什么问题",
        "怎样解决": "怎样解决",
        "解决方案": "怎样解决",
        "核心指标解决方案": "怎样解决",
        "solvewhatans": "怎样解决",
    },
}


def _infer_target_form(raw_target_form: str, field_name: str, value: Any) -> str:
    target = (raw_target_form or "").strip()
    if target in {"客户主表", "预期表", "场景表"}:
        return target
    normalized = _normalize_key(field_name)
    text_value = str(value or "")
    if any(k in normalized for k in ["detailbrief", "预期简述", "预期详情", "detail", "yuqi", "推进想法"]):
        return "预期表"
    if any(k in normalized for k in ["title", "场景", "solvewhatques", "solvewhatans", "解决什么问题", "怎样解决"]):
        return "场景表"
    if "【预期背景】" in text_value or "【预期需求内容】" in text_value:
        return "预期表"
    if "现状" in text_value and "痛点" in text_value and ("目标" in text_value or "效果" in text_value):
        return "场景表"
    return "未知"


def _resolve_field_rule(target_form: str, raw_field_name: str, form_cfg: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    field_mapping = form_cfg.get("field_mapping") or {}
    if not field_mapping:
        return None, {}

    # 1) direct exact key
    if raw_field_name in field_mapping:
        return raw_field_name, field_mapping[raw_field_name]

    normalized_field_name = _normalize_key(raw_field_name)
    # 2) normalized exact match against configured keys
    for configured_name, rule in field_mapping.items():
        if _normalize_key(configured_name) == normalized_field_name:
            return configured_name, rule

    # 3) alias map
    alias_map = FIELD_ALIASES.get(target_form, {})
    canonical_name = alias_map.get(normalized_field_name)
    if canonical_name and canonical_name in field_mapping:
        return canonical_name, field_mapping[canonical_name]

    # 4) fallback by obvious keyword semantics
    if target_form == "预期表":
        if "状态" in raw_field_name and "预期状态" in field_mapping:
            return "预期状态", field_mapping["预期状态"]
        if ("简述" in raw_field_name or "摘要" in raw_field_name) and "预期简述" in field_mapping:
            return "预期简述", field_mapping["预期简述"]
        if "预期详情" in field_mapping:
            return "预期详情", field_mapping["预期详情"]
    if target_form == "场景表":
        if ("标题" in raw_field_name or "场景" in raw_field_name) and "场景标题" in field_mapping:
            return "场景标题", field_mapping["场景标题"]
        if ("问题" in raw_field_name or "痛点" in raw_field_name or "诉求" in raw_field_name) and "解决什么问题" in field_mapping:
            return "解决什么问题", field_mapping["解决什么问题"]
        if "怎样解决" in field_mapping:
            return "怎样解决", field_mapping["怎样解决"]

    return None, {}

TOOL_EXTRACT_FACTS = {
    "name": "extract_customer_facts",
    "description": "提炼客户预期与业务场景，输出去重后的结构化事实（非逐句切片）。",
    "input_schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "description": "提取到的事实列表。每条都应是可行动的预期/场景结论，而非原文碎片。",
                "items": {
                    "type": "object",
                    "properties": {
                        "field_name": {
                            "type": "string",
                            "description": "字段名称，建议使用如“客户预期-目标”“业务场景-当前流程”“业务场景-痛点”等中文命名。",
                        },
                        "value": {
                            "type": "string",
                            "description": "归纳后的完整事实值，不要逐句抄写，不要只给关键词切片。",
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "置信度。"},
                        "source_quote": {"type": "string", "description": "来源引用或图片位置描述。"},
                        "source_type": {
                            "type": "string",
                            "enum": ["text", "image"],
                            "description": "事实来源类型：文本或图片。",
                        },
                        "category": {
                            "type": "string",
                            "enum": [
                                "company_info",
                                "contact_person",
                                "requirements",
                                "feedback",
                                "renewal_intent",
                                "competitor_mention",
                                "action_items",
                                "risk_signals",
                            ],
                            "description": "内部语义分类。",
                        },
                        "target_form": {
                            "type": "string",
                            "enum": ["客户主表", "预期表", "场景表", "未知"],
                            "description": "该事实建议落在哪张表。",
                        },
                    },
                    "required": ["field_name", "value", "confidence", "source_quote", "source_type", "category"],
                },
            }
        },
        "required": ["facts"],
    },
}

TOOL_FETCH_PROFILE = {
    "name": "fetch_customer_profile",
    "description": "在比对前读取客户当前档案信息（当前为 mock 返回）。",
    "input_schema": {
        "type": "object",
        "properties": {
            "company_id": {"type": "string", "description": "客户唯一 ID。"},
            "fields": {"type": "array", "items": {"type": "string"}, "description": "指定返回字段列表。"},
        },
        "required": ["company_id"],
    },
}

TOOL_COMPARE_OPS = {
    "name": "compare_and_generate_operations",
    "description": "将新事实与现有档案比对，生成 create/update/conflict 操作卡片。",
    "input_schema": {
        "type": "object",
        "properties": {
            "extracted_facts": {"type": "array", "items": {"type": "object"}},
            "existing_profile": {"type": "object", "description": "客户当前档案数据。"},
        },
        "required": ["extracted_facts", "existing_profile"],
    },
}

TOOL_CHAT_QUERY_RECORDS = {
    "name": "query_customer_records",
    "description": "查询指定客户在预期表或场景表中的已有记录，用于 update/delete 前确认目标",
    "input_schema": {
        "type": "object",
        "properties": {
            "company_id": {"type": "string", "description": "客户简道云 _id"},
            "target_form": {"type": "string", "enum": ["预期表", "场景表"]},
        },
        "required": ["company_id", "target_form"],
    },
}

TOOL_CHAT_CREATE_RECORD = {
    "name": "create_customer_record",
    "description": "在预期表或场景表中新增一条完整记录。一次调用应在 fields 中提供该记录的全部关键字段（如标题、问题、方案）。lookup 字段自动填入，不需要指定。",
    "input_schema": {
        "type": "object",
        "properties": {
            "company_id": {"type": "string"},
            "target_form": {"type": "string", "enum": ["预期表", "场景表"]},
            "fields": {"type": "object", "additionalProperties": {"type": "string"}},
        },
        "required": ["company_id", "target_form", "fields"],
    },
}

TOOL_CHAT_UPDATE_RECORD = {
    "name": "update_customer_record",
    "description": "修改预期表或场景表中的一条已有记录。一次调用可提交该记录多个字段变更。",
    "input_schema": {
        "type": "object",
        "properties": {
            "company_id": {"type": "string"},
            "target_form": {"type": "string", "enum": ["预期表", "场景表"]},
            "data_id": {"type": "string", "description": "目标记录的简道云 _id，必须先通过 query_customer_records 获取"},
            "fields": {"type": "object", "additionalProperties": {"type": "string"}},
        },
        "required": ["company_id", "target_form", "data_id", "fields"],
    },
}

TOOL_CHAT_DELETE_RECORD = {
    "name": "delete_customer_record",
    "description": "删除预期表或场景表中的一条记录",
    "input_schema": {
        "type": "object",
        "properties": {
            "company_id": {"type": "string"},
            "target_form": {"type": "string", "enum": ["预期表", "场景表"]},
            "data_id": {"type": "string", "description": "目标记录的简道云 _id"},
        },
        "required": ["company_id", "target_form", "data_id"],
    },
}


async def exec_extract_facts(params: dict[str, Any]) -> dict[str, Any]:
    facts = params.get("facts", [])
    return {"facts": facts, "total_extracted": len(facts)}


async def exec_fetch_profile_mock(params: dict[str, Any]) -> dict[str, Any]:
    company_id = params["company_id"]
    return {
        "_mock": True,
        "_id": company_id,
        "comname_01": f"示例公司-{company_id[:6]}",
        "com_type": "直销用户",
        "revenue_level": "头部客户",
        "if_access": "是",
        "follow_form": "月度回访",
        "_widget_1773297739599": [{"进度详情": "已完成第一阶段", "日期": "2026-04-24T00:00:00.000Z"}],
        "客户标签": ["高潜", "重点跟进"],
    }


async def exec_fetch_profile(params: dict[str, Any]) -> dict[str, Any]:
    runtime_cfg = params.get("runtime_cfg", {}) or {}
    mapping = runtime_cfg.get("mapping", {}) or {}
    forms = mapping.get("forms", {}) or {}
    api_key = (runtime_cfg.get("api_key") or "").strip()
    app_id = (runtime_cfg.get("app_id") or "").strip()
    company_id = params.get("company_id")
    company_name = str(params.get("company_name") or "").strip()
    if not api_key or not app_id:
        return await exec_fetch_profile_mock(params)
    client = JiandaoyunClient(api_key=api_key)
    main_form = forms.get("客户主表", {})
    yuqi_form = forms.get("预期表", {})
    changjing_form = forms.get("场景表", {})
    warning = None
    try:
        if not company_id and company_name:
            match_result = await match_customer(client, app_id, str(main_form.get("entry_id", "")), company_name, limit=5)
            candidates = match_result.candidates
            if match_result.status == "not_found" or not candidates:
                return {"_mock": False, "_id": None, "profile": {}, "yuqi": [], "changjing": [], "warning": "客户未匹配"}
            if match_result.status == "multiple":
                warning = "多客户匹配，使用第一条候选"
            company_id = candidates[0].get("_id")
        if not company_id:
            return {"_mock": False, "_id": None, "profile": {}, "yuqi": [], "changjing": [], "warning": "客户未匹配"}
        profile = None
        try:
            profile = await client.query_single_data(app_id, str(main_form.get("entry_id", "")), str(company_id))
        except JiandaoyunClientError:
            # Common fallback: frontend may pass local hash ID; recover by matching company name.
            if company_name:
                match_result = await match_customer(client, app_id, str(main_form.get("entry_id", "")), company_name, limit=5)
                candidates = match_result.candidates
                if candidates:
                    if match_result.status == "multiple":
                        warning = "多客户匹配，使用第一条候选"
                    company_id = candidates[0].get("_id")
                    profile = await client.query_single_data(app_id, str(main_form.get("entry_id", "")), str(company_id))
            if profile is None:
                raise
        yuqi = await client.query_data_list(
            app_id=app_id,
            entry_id=str(yuqi_form.get("entry_id", "")),
            filter_condition={
                "rel": "and",
                "cond": [{"field": str((yuqi_form.get("lookup_customer") or {}).get("widget") or "relation"), "type": "lookup", "method": "eq", "value": [company_id]}],
            },
            limit=100,
        )
        changjing = await client.query_data_list(
            app_id=app_id,
            entry_id=str(changjing_form.get("entry_id", "")),
            filter_condition={
                "rel": "and",
                "cond": [{"field": str((changjing_form.get("lookup_customer") or {}).get("widget") or "_widget_1737335801798"), "type": "lookup", "method": "eq", "value": [company_id]}],
            },
            limit=100,
        )
        return {"_mock": False, "_id": company_id, "profile": profile.get("data", {}), "yuqi": yuqi.get("data", []), "changjing": changjing.get("data", []), "warning": warning}
    except JiandaoyunClientError:
        return await exec_fetch_profile_mock(params)


async def exec_compare_ops_mock(params: dict[str, Any]) -> dict[str, Any]:
    # 仅演示用，字段名不代表简道云真实表单
    # TODO: 替换为简道云真实调用
    facts = params.get("extracted_facts", [])
    profile = params.get("existing_profile", {})
    cards: list[dict[str, Any]] = []
    for fact in facts:
        field_name = str(fact.get("field_name", "")).strip()
        if not field_name:
            continue
        old_val = profile.get(field_name)
        new_val = str(fact.get("value", "")).strip()
        if not new_val:
            continue
        if old_val is None:
            op_type = "create"
        elif str(old_val) != new_val:
            op_type = "update"
        else:
            continue
        cards.append(
            {
                "field_name": field_name,
                "operation_type": op_type,
                "old_value": str(old_val) if old_val is not None else None,
                "new_value": new_val,
                "confidence": float(fact.get("confidence", 0.8)),
                "source_quote": str(fact.get("source_quote", "mock source")),
                "target_form": str(fact.get("target_form", "未知")),
                "safety_status": "unknown",
                "safety_reason": "mock comparison result",
            }
        )
    return {"operation_cards": cards, "total": len(cards)}


async def exec_compare_ops(params: dict[str, Any]) -> dict[str, Any]:
    facts = params.get("extracted_facts", []) or []
    existing = params.get("existing_profile", {}) or {}
    runtime_cfg = params.get("runtime_cfg", {}) or {}
    mapping = (runtime_cfg.get("mapping", {}) or {}).get("forms", {}) or {}
    primary_field_by_form = {"预期表": "预期简述", "场景表": "场景标题"}
    existing_rows_by_form = {
        "预期表": list(existing.get("yuqi") or []),
        "场景表": list(existing.get("changjing") or []),
    }

    def _normalized(text: Any) -> str:
        return _normalize_key(str(text or ""))

    def _similarity(left: Any, right: Any) -> float:
        a = _normalized(left)
        b = _normalized(right)
        if not a or not b:
            return 0.0
        if a in b or b in a:
            return 1.0
        return SequenceMatcher(None, a, b).ratio()

    def _match_existing_row(target_form: str, primary_widget: str, primary_value: str) -> dict[str, Any] | None:
        threshold = 0.82
        best_score = 0.0
        best_row: dict[str, Any] | None = None
        for row in existing_rows_by_form.get(target_form, []):
            score = _similarity(row.get(primary_widget), primary_value)
            if score > best_score:
                best_score = score
                best_row = row
        if best_score >= threshold:
            return best_row
        return None

    grouped: dict[str, dict[str, Any]] = {}
    last_group_key_by_form: dict[str, str] = {}

    for fact in facts:
        raw_field_name = str(fact.get("field_name") or "").strip()
        if not raw_field_name:
            continue
        target_form = _infer_target_form(str(fact.get("target_form") or "未知"), raw_field_name, fact.get("value"))
        if target_form not in {"预期表", "场景表"}:
            continue
        form_cfg = mapping.get(target_form, {})
        if not form_cfg:
            continue
        canonical_field_name, field_map = _resolve_field_rule(target_form, raw_field_name, form_cfg)
        if not canonical_field_name:
            continue
        widget_name = str((field_map or {}).get("widget") or "")
        if not widget_name:
            continue
        new_value = str(fact.get("value") if fact.get("value") is not None else "").strip()
        if not new_value:
            continue

        primary_field = primary_field_by_form[target_form]
        if canonical_field_name == primary_field:
            group_key = f"{target_form}:{_normalized(new_value)}"
            if group_key not in grouped:
                grouped[group_key] = {
                    "card_id": str(uuid4()),
                    "target_form": target_form,
                    "confidence": 0.0,
                    "source_quote": "",
                    "review_status": "pending",
                    "execute_status": "pending",
                    "customer_id": existing.get("_id"),
                    "lookup_widget": str((form_cfg.get("lookup_customer") or {}).get("widget") or ""),
                    "form_cfg": form_cfg,
                    "primary_field": primary_field,
                    "primary_widget": widget_name,
                    "primary_value": new_value,
                    "item_by_field": {},
                }
            last_group_key_by_form[target_form] = group_key
        else:
            # Non-primary fields belong to the most recent primary in this form.
            group_key = last_group_key_by_form.get(target_form)
            if not group_key:
                continue

        current = grouped[group_key]
        current["confidence"] = max(float(current.get("confidence") or 0.0), float(fact.get("confidence", 0.8)))
        quote = str(fact.get("source_quote", "")).strip()
        if quote:
            current["source_quote"] = f"{current['source_quote']}\n{quote}".strip() if current["source_quote"] else quote

        # One field appears at most once in each card.
        previous = current["item_by_field"].get(canonical_field_name)
        if previous is None or float(fact.get("confidence", 0.0)) >= float(previous.get("_confidence", 0.0)):
            current["item_by_field"][canonical_field_name] = {
                "field_name": canonical_field_name,
                "widget_name": widget_name,
                "new_value": new_value,
                "_confidence": float(fact.get("confidence", 0.0)),
            }

    cards: list[dict[str, Any]] = []
    for grouped_card in grouped.values():
        target_form = str(grouped_card.get("target_form") or "")
        form_cfg = grouped_card.get("form_cfg") or mapping.get(target_form, {})
        item_by_field = grouped_card.get("item_by_field") or {}
        primary_field = str(grouped_card.get("primary_field") or "")
        primary_widget = str(grouped_card.get("primary_widget") or "")
        primary_value = str(grouped_card.get("primary_value") or "")
        if not item_by_field or not primary_field or not primary_value:
            continue

        matched_row = _match_existing_row(target_form, primary_widget, primary_value)
        op_type = "update" if matched_row else "create"
        data_id = str((matched_row or {}).get("_id") or "") or None
        if op_type == "update" and not data_id:
            # update must have data_id; fallback to create otherwise.
            op_type = "create"

        change_items: list[dict[str, Any]] = []
        for field_name, item in item_by_field.items():
            widget_name = str(item.get("widget_name") or "")
            old_raw = (matched_row or {}).get(widget_name) if matched_row else None
            change_items.append(
                {
                    "field_name": field_name,
                    "widget_name": widget_name,
                    "old_value": None if op_type == "create" else (None if old_raw is None else str(old_raw)),
                    "new_value": str(item.get("new_value") or ""),
                }
            )

        card = {
            "card_id": grouped_card.get("card_id") or str(uuid4()),
            "target_form": target_form,
            "operation_type": op_type,
            "confidence": float(grouped_card.get("confidence") or 0.0),
            "source_quote": str(grouped_card.get("source_quote") or ""),
            "review_status": "pending",
            "execute_status": "pending",
            "data_id": data_id if op_type == "update" else None,
            "customer_id": existing.get("_id"),
            "lookup_widget": str(grouped_card.get("lookup_widget") or ""),
            "change_items": change_items,
        }
        safe = check_operation_cards([card], form_cfg)[0]
        cards.append(safe)
    return {"operation_cards": cards, "total": len(cards)}


async def _exec_chat_query_records(params: dict[str, Any], runtime_cfg: dict[str, Any]) -> dict[str, Any]:
    mapping = (runtime_cfg.get("mapping") or {}).get("forms", {}) or {}
    target_form = str(params.get("target_form") or "")
    company_id = str(params.get("company_id") or "")
    form_cfg = mapping.get(target_form, {}) or {}
    entry_id = str(form_cfg.get("entry_id") or "")
    lookup_widget = str((form_cfg.get("lookup_customer") or {}).get("widget") or "")
    api_key = str(runtime_cfg.get("api_key") or "").strip()
    app_id = str(runtime_cfg.get("app_id") or "").strip()
    if not (company_id and entry_id and lookup_widget and api_key and app_id):
        return {"records": [], "total": 0, "warning": "缺少查询必要配置"}
    client = JiandaoyunClient(api_key=api_key)
    page = await client.query_data_list(
        app_id=app_id,
        entry_id=entry_id,
        filter_condition={"rel": "and", "cond": [{"field": lookup_widget, "type": "lookup", "method": "eq", "value": [company_id]}]},
        limit=20,
    )
    data = page.get("data", []) or []
    return {"records": data, "total": len(data)}


def build_chat_executors(runtime_cfg: dict[str, Any]) -> dict[str, ToolExecutor]:
    async def query_customer_records(params: dict[str, Any]) -> dict[str, Any]:
        return await _exec_chat_query_records(params, runtime_cfg)

    async def create_customer_record(params: dict[str, Any]) -> dict[str, Any]:
        return {"accepted": True, "pending_only": True, "tool_input": params}

    async def update_customer_record(params: dict[str, Any]) -> dict[str, Any]:
        return {"accepted": True, "pending_only": True, "tool_input": params}

    async def delete_customer_record(params: dict[str, Any]) -> dict[str, Any]:
        return {"accepted": True, "pending_only": True, "tool_input": params}

    return {
        "query_customer_records": query_customer_records,
        "create_customer_record": create_customer_record,
        "update_customer_record": update_customer_record,
        "delete_customer_record": delete_customer_record,
    }


def get_chat_tools() -> list[dict[str, Any]]:
    return [
        TOOL_CHAT_QUERY_RECORDS,
        TOOL_CHAT_CREATE_RECORD,
        TOOL_CHAT_UPDATE_RECORD,
        TOOL_CHAT_DELETE_RECORD,
    ]


_REGISTRY: dict[str, dict[str, Any]] = {
    "extraction": {
        "tools": [TOOL_EXTRACT_FACTS],
        "executors": {"extract_customer_facts": exec_extract_facts},
    },
    "comparison": {
        "tools": [TOOL_FETCH_PROFILE, TOOL_COMPARE_OPS],
        "executors": {
            "fetch_customer_profile": exec_fetch_profile,
            "compare_and_generate_operations": exec_compare_ops,
        },
    },
}


def get_tools(phase: str) -> list[dict[str, Any]]:
    return _REGISTRY[phase]["tools"]


def get_executors(phase: str) -> dict[str, ToolExecutor]:
    return _REGISTRY[phase]["executors"]

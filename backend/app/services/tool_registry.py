from __future__ import annotations

from uuid import uuid4
from typing import Any, Awaitable, Callable
import json
import re
from difflib import SequenceMatcher

import httpx

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
        "是否第一价值实现预期": "是否第一价值实现预期",
        "是否第一价值": "是否第一价值实现预期",
        "第一价值": "是否第一价值实现预期",
        "第一价值实现": "是否第一价值实现预期",
        "isfirstvalue": "是否第一价值实现预期",
        "_widget_1770346583096": "是否第一价值实现预期",
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
        if ("第一价值" in raw_field_name or "价值" in raw_field_name) and "是否第一价值实现预期" in field_mapping:
            return "是否第一价值实现预期", field_mapping["是否第一价值实现预期"]
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
    """LLM 驱动的比对：用 LLM 判断每条提取内容与已有记录的关系（create/update/skip）。

    params 除原有字段外，新增：
      llm_cfg: dict 包含 provider / api_key / model_name / base_url
      agent_b_prompt: str | None — LLM 的 system prompt 模板
    """
    return await exec_compare_ops_llm(params)


async def exec_compare_ops_llm(params: dict[str, Any]) -> dict[str, Any]:
    facts = params.get("extracted_facts", []) or []
    existing = params.get("existing_profile", {}) or {}
    runtime_cfg = params.get("runtime_cfg", {}) or {}
    llm_cfg = params.get("llm_cfg") or {}
    mapping = (runtime_cfg.get("mapping", {}) or {}).get("forms", {}) or {}
    primary_field_by_form = {"预期表": "预期简述", "场景表": "场景标题"}
    existing_rows_by_form = {
        "预期表": list(existing.get("yuqi") or []),
        "场景表": list(existing.get("changjing") or []),
    }

    # ---------- 1. 先用纯 Python 构建 grouped cards（保持原有分组逻辑） ----------
    def _normalized(text: Any) -> str:
        return _normalize_key(str(text or ""))

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
            group_key = last_group_key_by_form.get(target_form)
            if not group_key:
                continue

        current = grouped[group_key]
        current["confidence"] = max(float(current.get("confidence") or 0.0), float(fact.get("confidence", 0.8)))
        quote = str(fact.get("source_quote", "")).strip()
        if quote:
            current["source_quote"] = f"{current['source_quote']}\n{quote}".strip() if current["source_quote"] else quote

        previous = current["item_by_field"].get(canonical_field_name)
        if previous is None or float(fact.get("confidence", 0.0)) >= float(previous.get("_confidence", 0.0)):
            current["item_by_field"][canonical_field_name] = {
                "field_name": canonical_field_name,
                "widget_name": widget_name,
                "new_value": new_value,
                "_confidence": float(fact.get("confidence", 0.0)),
            }

    if not grouped:
        return {"operation_cards": [], "total": 0}

    # ---------- 2. 如果有 llm_cfg，尝试 LLM 比对 ----------
    use_llm = bool(llm_cfg.get("api_key") and llm_cfg.get("base_url"))
    llm_result = None
    if use_llm:
        try:
            llm_result = await _call_llm_comparison(
                llm_cfg=llm_cfg,
                grouped=grouped,
                existing_rows_by_form=existing_rows_by_form,
                primary_field_by_form=primary_field_by_form,
                mapping=mapping,
                existing=existing,
                user_prompt_override=params.get("agent_b_prompt"),
            )
        except Exception as exc:
            import logging
            logger = logging.getLogger("zhidang")
            logger.warning("LLM comparison failed, falling back to string matching: %s", exc)

    # ---------- 3. 如果 LLM 成功，用 LLM 结果；否则回退到原逻辑 ----------
    cards: list[dict[str, Any]] = []
    if llm_result and llm_result.get("decisions"):
        # LLM 模式
        cards = _build_cards_from_llm_decisions(
            grouped=grouped,
            decisions=llm_result["decisions"],
            existing_rows_by_form=existing_rows_by_form,
            existing=existing,
            mapping=mapping,
        )
    else:
        # 回退：纯字符串匹配原逻辑
        cards = _build_cards_by_string_match(
            grouped=grouped,
            existing_rows_by_form=existing_rows_by_form,
            existing=existing,
            mapping=mapping,
        )

    return {"operation_cards": cards, "total": len(cards)}


import asyncio as _asyncio
import logging as _logging

_comparison_logger = _logging.getLogger("zhidang.comparison")
_shared_llm_client: httpx.AsyncClient | None = None
_shared_llm_lock = _asyncio.Lock()


async def _get_shared_llm_client() -> httpx.AsyncClient:
    """获取或创建共享的 httpx 客户端，复用连接池。"""
    global _shared_llm_client
    async with _shared_llm_lock:
        if _shared_llm_client is None or _shared_llm_client.is_closed:
            _shared_llm_client = httpx.AsyncClient(timeout=httpx.Timeout(7200, connect=120))
        return _shared_llm_client


async def _llm_post_with_retry(url: str, headers: dict, payload: dict, max_retries: int = 2) -> httpx.Response:
    """带重试的 LLM HTTP POST，复用连接池。"""
    client = await _get_shared_llm_client()
    last_exc: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 500:
                raise RuntimeError(f"服务端错误 HTTP {resp.status_code}")
            return resp
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, RuntimeError) as exc:
            last_exc = exc
            if attempt < max_retries:
                wait = 1.5 * (2 ** attempt)
                _comparison_logger.warning("比较 LLM 请求失败 (尝试 %d/%d)，%.1fs 后重试: %s", attempt + 1, 1 + max_retries, wait, exc)
                await _asyncio.sleep(wait)
                # 重建 client
                async with _shared_llm_lock:
                    if _shared_llm_client and not _shared_llm_client.is_closed:
                        await _shared_llm_client.aclose()
                    _shared_llm_client = None
                client = await _get_shared_llm_client()
    raise RuntimeError(f"比较 LLM 请求重试 {max_retries} 次后仍失败: {last_exc}")


def _compact_text(value: Any, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else f"{text[:limit]}..."


def _grouped_card_text(card: dict[str, Any]) -> str:
    values = [str(card.get("primary_value") or "")]
    for item in (card.get("item_by_field") or {}).values():
        val = str(item.get("new_value") or "").strip()
        if val and val not in values:
            values.append(val)
    return " ".join(values)


def _yuqi_row_summary(row: dict[str, Any], mapping: dict[str, Any]) -> str:
    primary_widget = (
        mapping.get("预期表", {})
        .get("field_mapping", {})
        .get("预期简述", {})
        .get("widget", "detail_brief")
    )
    return str(
        row.get(primary_widget)
        or row.get("detail_brief")
        or row.get("detail")
        or row.get("_id")
        or ""
    ).strip()


def _clean_optional_id(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "null", "none", "无", "不关联"} else text


def _resolve_related_yuqi_from_decision(
    *,
    decision: dict[str, Any],
    grouped: dict[str, dict[str, Any]],
    decisions_by_group_key: dict[str, dict[str, Any]],
    existing_rows_by_form: dict[str, list[dict[str, Any]]],
    mapping: dict[str, Any],
) -> dict[str, Any]:
    reason = str(decision.get("related_yuqi_reason") or decision.get("relation_reason") or "").strip()
    confidence_raw = decision.get("related_yuqi_confidence")
    confidence: float | None = None
    try:
        if confidence_raw is not None:
            confidence = max(0.0, min(1.0, float(confidence_raw)))
    except (TypeError, ValueError):
        confidence = None

    related_id = _clean_optional_id(
        decision.get("related_yuqi_id")
        or decision.get("related_expectation_id")
        or decision.get("related_record_id")
    )
    if related_id:
        for row in existing_rows_by_form.get("预期表", []):
            if str(row.get("_id") or "") == related_id:
                return {
                    "related_yuqi_id": related_id,
                    "related_yuqi_card_id": None,
                    "related_yuqi_source": "existing",
                    "related_yuqi_summary": _compact_text(_yuqi_row_summary(row, mapping)),
                    "related_yuqi_reason": reason,
                    "related_yuqi_confidence": confidence,
                }

    group_keys = list(grouped.keys())
    related_group_key = _clean_optional_id(decision.get("related_yuqi_group_key"))
    related_index = decision.get("related_yuqi_index") or decision.get("related_expectation_index")
    if not related_group_key and related_index not in (None, ""):
        try:
            idx = int(str(related_index).strip()) - 1
            if 0 <= idx < len(group_keys):
                related_group_key = group_keys[idx]
        except (TypeError, ValueError):
            related_group_key = ""

    if related_group_key and related_group_key in grouped:
        target = grouped[related_group_key]
        target_decision = decisions_by_group_key.get(related_group_key) or {}
        if target.get("target_form") == "预期表" and target_decision.get("operation") in {"create", "update"}:
            return {
                "related_yuqi_id": None,
                "related_yuqi_card_id": target.get("card_id"),
                "related_yuqi_source": "generated",
                "related_yuqi_summary": _compact_text(target.get("primary_value")),
                "related_yuqi_reason": reason,
                "related_yuqi_confidence": confidence,
            }

    return {}


async def _call_llm_comparison(
    *,
    llm_cfg: dict[str, str],
    grouped: dict[str, dict[str, Any]],
    existing_rows_by_form: dict[str, list[dict[str, Any]]],
    primary_field_by_form: dict[str, str],
    mapping: dict[str, Any],
    existing: dict[str, Any],
    user_prompt_override: str | None = None,
) -> dict[str, Any]:
    """调用 OpenAI-compatible API 做语义比对。

    返回 {"decisions": [...]}，每个 decision 包含：
      - group_key: 对应 grouped 中的 key
      - operation: "create" | "update" | "skip"
      - matched_record_id: str | None (update 时必需)
      - reason: str
    """
    base_url = llm_cfg.get("base_url", "").rstrip("/")
    api_key = llm_cfg.get("api_key", "")
    model_name = llm_cfg.get("model_name", "")

    # 构建已有记录的可读摘要
    existing_summaries = []
    for form_name in ["预期表", "场景表"]:
        rows = existing_rows_by_form.get(form_name, [])
        if not rows:
            existing_summaries.append(f"【{form_name}】无已有记录")
            continue
        existing_summaries.append(f"【{form_name}】（共 {len(rows)} 条）：")
        for row in rows:
            primary_widget = mapping.get(form_name, {}).get("field_mapping", {}).get(primary_field_by_form[form_name], {}).get("widget", "")
            summary = row.get(primary_widget) or row.get("detail_brief") or row.get("title") or str(row.get("_id", ""))
            detail = row.get("detail") or row.get("solve_what_ques") or ""
            status = row.get("yuqi_status") or row.get("status") or ""
            detail_snippet = f" | 详情: {detail[:200]}" if detail else ""
            existing_summaries.append(f"  - _id: {row.get('_id')} | 摘要: {summary} | 状态: {status}{detail_snippet}")
    existing_text = "\n".join(existing_summaries)

    # 构建待比对的新数据描述
    new_items_lines = []
    for idx, (gk, card) in enumerate(grouped.items(), start=1):
        target_form = card.get("target_form", "未知")
        primary_value = card.get("primary_value", "")
        non_primary = [
            f"{v.get('field_name', '')}: {v.get('new_value', '')}"
            for fk, v in card.get("item_by_field", {}).items()
            if fk != card.get("primary_field")
        ]
        extras = "；".join(non_primary) if non_primary else ""
        new_items_lines.append(f"  {idx}. group_key: {gk} | 表单: {target_form} | 核心: {primary_value} | 额外字段: {extras}")
    new_items_text = "\n".join(new_items_lines)

    # system prompt
    default_system_prompt = """你是一个客户档案管理专家，负责将新提取的客户预期和场景与简道云中已有的档案数据进行智能比对，生成精确的操作指令。

## 你的任务
对比「新提取的数据」和「已有档案数据」，判断每条提取内容应该执行什么操作。

## 操作类型判断规则
1. **新增（create）**：提取内容在已有档案中无语义相似项，调用 `create` 操作
2. **更新（update）**：提取内容与已有档案某条记录语义高度相似，但有新信息需要补充或状态需要变更，调用 `update` 操作，并填写 matched_record_id 指向已有记录
3. **跳过（skip）**：提取内容与已有记录完全重复且无新信息

## 相似度判断原则
- 基于语义，不要求字面完全一致
- 例如「希望提升审批效率」和「审批流程太慢需要优化」应视为相似
- update 时，只有真正有新信息才标记为 update，仅措辞差异不算新信息
- 如果核心内容判断为已存在且没有新增有价值的信息，应为 skip

## 输出格式
你必须仅返回一个 JSON 数组，不要包含其他内容：

```json
[
  {
    "operation": "create | update | skip",
    "matched_record_id": null,
    "related_yuqi_id": null,
    "related_yuqi_index": null,
    "related_yuqi_reason": "",
    "related_yuqi_confidence": null,
    "reason": "判断理由"
  }
]
```

注意：
- 数组顺序与输入的新数据顺序一致
- matched_record_id 只在 update 时填写已有记录的完整 _id（例如 '67f9002404ad14d923d362fb'），create/skip 时为 null
- 只有“场景表”条目需要判断 related_yuqi：如果关联已有预期，填写 related_yuqi_id；如果关联本次新提取的预期，填写 related_yuqi_index（输入序号，1 开始）；无法确定时都填 null
- reason 必须用中文说明判断依据"""

    association_prompt = """## 场景关联预期规则
- 每条“场景表”数据都要额外判断是否属于某条客户预期下的具体落地场景。
- 可以关联“已有档案数据”里的预期，也可以关联“新提取的数据”里同批生成的预期。
- 关联已有预期时，填写 related_yuqi_id 为该预期完整 _id。
- 关联本次生成预期时，填写 related_yuqi_index 为输入列表里的预期序号；不要填写场景序号。
- 只有当场景是某个预期的具体执行、应用、方案、流程或指标承接时才关联；只是同属一个客户或弱相关时不要关联。
- related_yuqi_reason 用一句中文说明为什么关联；related_yuqi_confidence 填 0 到 1 的置信度。"""

    user_prompt = f"""## 已有档案数据

{existing_text}

## 新提取的数据（按条目序号排列，每个序号对应一条预期或场景）

{new_items_text}

请逐条判断每条新数据与已有档案的关系（create / update / skip），按相同顺序返回 JSON 数组。"""

    system_prompt = f"{user_prompt_override or default_system_prompt}\n\n{association_prompt}"

    url = f"{base_url}/chat/completions"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model_name, "messages": messages, "temperature": 0.1, "max_tokens": 4096}

    resp = await _llm_post_with_retry(url, headers, payload)

    if resp.status_code >= 400:
        raise RuntimeError(f"LLM comparison call failed: HTTP {resp.status_code} {resp.text[:200]}")

    data = resp.json()
    text = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
    if not text:
        raise RuntimeError("LLM returned empty content")

    raw = text.strip()
    # 去除 markdown code block
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    decisions = json.loads(raw)
    if not isinstance(decisions, list):
        raise RuntimeError(f"LLM did not return an array: {type(decisions)}")

    # 验证决策数与 grouped 数一致
    group_keys = list(grouped.keys())
    if len(decisions) != len(group_keys):
        raise RuntimeError(f"LLM returned {len(decisions)} decisions, expected {len(group_keys)}")

    # 挂载 group_key
    for i, gk in enumerate(group_keys):
        decisions[i]["group_key"] = gk

    # 兜底：如果 LLM 全判 create 但明明有已有记录，回退到字符串匹配
    all_create = all(d.get("operation") == "create" for d in decisions)
    has_existing = any(len(rows) > 0 for rows in existing_rows_by_form.values())
    has_related_yuqi = any(
        _clean_optional_id(
            d.get("related_yuqi_id")
            or d.get("related_expectation_id")
            or d.get("related_record_id")
            or d.get("related_yuqi_group_key")
        )
        or d.get("related_yuqi_index")
        or d.get("related_expectation_index")
        for d in decisions
    )
    if all_create and has_existing and not has_related_yuqi:
        import logging
        logger = logging.getLogger("zhidang")
        logger.warning("LLM returned all-create but existing records found, raw decisions: %s", json.dumps(decisions, ensure_ascii=False)[:500])
        raise RuntimeError("LLM returned all-create with existing records, falling back")

    return {"decisions": decisions}


def _build_cards_from_llm_decisions(
    grouped: dict[str, dict[str, Any]],
    decisions: list[dict[str, Any]],
    existing_rows_by_form: dict[str, list[dict[str, Any]]],
    existing: dict[str, Any],
    mapping: dict[str, Any],
) -> list[dict[str, Any]]:
    """根据 LLM 的 decisions 构建 operation_cards。"""
    cards: list[dict[str, Any]] = []
    decisions_by_group_key = {str(item.get("group_key") or ""): item for item in decisions}

    for decision in decisions:
        gk = decision.get("group_key")
        operation = decision.get("operation", "skip")
        if operation == "skip":
            continue
        grouped_card = grouped.get(gk)
        if not grouped_card:
            continue

        target_form = str(grouped_card.get("target_form") or "")
        form_cfg = grouped_card.get("form_cfg") or mapping.get(target_form, {})
        item_by_field = grouped_card.get("item_by_field") or {}
        primary_value = str(grouped_card.get("primary_value") or "")

        if not item_by_field or not primary_value:
            continue

        # 找到匹配的已有记录
        matched_row = None
        matched_id = decision.get("matched_record_id")
        if operation == "update" and matched_id:
            for row in existing_rows_by_form.get(target_form, []):
                if str(row.get("_id", "")) == matched_id:
                    matched_row = row
                    break

        change_items: list[dict[str, Any]] = []
        for field_name, item in item_by_field.items():
            widget_name = str(item.get("widget_name") or "")
            old_raw = (matched_row or {}).get(widget_name) if matched_row else None
            change_items.append({
                "field_name": field_name,
                "widget_name": widget_name,
                "old_value": None if operation == "create" else (None if old_raw is None else str(old_raw)),
                "new_value": str(item.get("new_value") or ""),
            })

        card = {
            "card_id": grouped_card.get("card_id") or str(uuid4()),
            "target_form": target_form,
            "operation_type": operation,
            "confidence": float(grouped_card.get("confidence") or 0.0),
            "source_quote": str(grouped_card.get("source_quote") or ""),
            "review_status": "pending",
            "execute_status": "pending",
            "data_id": (matched_row or {}).get("_id") if operation == "update" else None,
            "customer_id": existing.get("_id"),
            "lookup_widget": str(grouped_card.get("lookup_widget") or ""),
            "change_items": change_items,
        }
        if target_form == "场景表":
            card.update(
                _resolve_related_yuqi_from_decision(
                    decision=decision,
                    grouped=grouped,
                    decisions_by_group_key=decisions_by_group_key,
                    existing_rows_by_form=existing_rows_by_form,
                    mapping=mapping,
                )
            )
        safe = check_operation_cards([card], form_cfg)[0]
        cards.append(safe)
    return cards


def _build_cards_by_string_match(
    grouped: dict[str, dict[str, Any]],
    existing_rows_by_form: dict[str, list[dict[str, Any]]],
    existing: dict[str, Any],
    mapping: dict[str, Any],
) -> list[dict[str, Any]]:
    """纯字符串相似度匹配（原 exec_compare_ops 逻辑保留作为回退）。"""
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

    def _match_existing_row(target_form, primary_widget, primary_value):
        threshold = 0.82
        best_score = 0.0
        best_row = None
        for row in existing_rows_by_form.get(target_form, []):
            score = _similarity(row.get(primary_widget), primary_value)
            if score > best_score:
                best_score = score
                best_row = row
        return best_row if best_score >= threshold else None

    def _best_related_yuqi(scene_card: dict[str, Any]) -> dict[str, Any]:
        scene_text = _grouped_card_text(scene_card)
        candidates: list[dict[str, Any]] = []

        for row in existing_rows_by_form.get("预期表", []):
            related_id = str(row.get("_id") or "").strip()
            if not related_id:
                continue
            summary = _yuqi_row_summary(row, mapping)
            candidates.append(
                {
                    "source": "existing",
                    "id": related_id,
                    "summary": summary,
                    "text": " ".join([summary, str(row.get("detail") or "")]),
                }
            )

        for candidate_card in grouped.values():
            if candidate_card.get("target_form") != "预期表":
                continue
            candidates.append(
                {
                    "source": "generated",
                    "card_id": candidate_card.get("card_id"),
                    "summary": str(candidate_card.get("primary_value") or ""),
                    "text": _grouped_card_text(candidate_card),
                }
            )

        best_score = 0.0
        best: dict[str, Any] | None = None
        for candidate in candidates:
            score = _similarity(scene_text, candidate.get("text", ""))
            if score > best_score:
                best_score = score
                best = candidate

        if not best or best_score < 0.42:
            return {}
        base = {
            "related_yuqi_source": best["source"],
            "related_yuqi_summary": _compact_text(best.get("summary")),
            "related_yuqi_reason": "根据场景内容与预期内容相似自动关联",
            "related_yuqi_confidence": round(best_score, 3),
        }
        if best["source"] == "existing":
            return {**base, "related_yuqi_id": best.get("id"), "related_yuqi_card_id": None}
        return {**base, "related_yuqi_id": None, "related_yuqi_card_id": best.get("card_id")}

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
            op_type = "create"

        change_items: list[dict[str, Any]] = []
        for field_name, item in item_by_field.items():
            widget_name = str(item.get("widget_name") or "")
            old_raw = (matched_row or {}).get(widget_name) if matched_row else None
            change_items.append({
                "field_name": field_name,
                "widget_name": widget_name,
                "old_value": None if op_type == "create" else (None if old_raw is None else str(old_raw)),
                "new_value": str(item.get("new_value") or ""),
            })

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
        if target_form == "场景表":
            card.update(_best_related_yuqi(grouped_card))
        safe = check_operation_cards([card], form_cfg)[0]
        cards.append(safe)
    return cards


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
    try:
        page = await client.query_data_list(
            app_id=app_id,
            entry_id=entry_id,
            filter_condition={"rel": "and", "cond": [{"field": lookup_widget, "type": "lookup", "method": "eq", "value": [company_id]}]},
            limit=20,
        )
        data = page.get("data", []) or []
        return {"records": data, "total": len(data)}
    except JiandaoyunClientError as exc:
        return {"records": [], "total": 0, "error": str(exc), "hint": "简道云 API 调用失败，可能是频率限制或配置问题，请稍后重试"}


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

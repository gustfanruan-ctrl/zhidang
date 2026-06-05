from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import OperationLog

OP_LABELS: dict[str, str] = {
    "create_customer_record": "新增",
    "update_customer_record": "修改",
    "delete_customer_record": "删除",
}

EXPECTATION_STATUS_FIELD = "预期状态"
EXPECTATION_STATUS_VALUES = ("未启动", "进行中", "已达成", "已作废")
EXPECTATION_STATUS_ALIASES = {
    "未启动": "未启动",
    "未开始": "未启动",
    "进行中": "进行中",
    "处理中": "进行中",
    "推进中": "进行中",
    "已达成": "已达成",
    "达成": "已达成",
    "完成": "已达成",
    "已完成": "已达成",
    "已作废": "已作废",
    "作废": "已作废",
    "结束": "已作废",
    "已结束": "已作废",
    "关闭": "已作废",
    "已关闭": "已作废",
}


class ChatPayloadValidationError(ValueError):
    """Raised when a chat maintenance payload cannot be normalized safely."""


def get_entry_id(target_form: str, mapping_forms: dict[str, Any]) -> str:
    form_cfg = (mapping_forms or {}).get(target_form, {}) or {}
    return str(form_cfg.get("entry_id") or "")


def _scene_customer_name_widget(form_cfg: dict[str, Any]) -> str:
    configured = form_cfg.get("customer_name_widget") or form_cfg.get("customer_name_helper")
    if isinstance(configured, dict):
        return str(configured.get("widget") or "")
    if isinstance(configured, str):
        return configured
    return "_widget_1743993204408"


def normalize_expectation_status_value(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ChatPayloadValidationError(
            f"{EXPECTATION_STATUS_FIELD} 不能为空；仅支持：{' / '.join(EXPECTATION_STATUS_VALUES)}"
        )
    if normalized in EXPECTATION_STATUS_VALUES:
        return normalized
    mapped = EXPECTATION_STATUS_ALIASES.get(normalized)
    if mapped:
        return mapped
    raise ChatPayloadValidationError(
        f"{EXPECTATION_STATUS_FIELD} 仅支持：{' / '.join(EXPECTATION_STATUS_VALUES)}"
    )


def build_jiandaoyun_payload(tool_input: dict[str, Any], form_config: dict[str, Any]) -> dict[str, Any]:
    fields = tool_input.get("fields", {}) or {}
    field_mapping = (form_config.get("field_mapping") or {}) if isinstance(form_config, dict) else {}
    payload: dict[str, Any] = {}
    target_form = str(tool_input.get("target_form") or "")
    for field_name, value in fields.items():
        mapping = field_mapping.get(str(field_name), {}) or {}
        widget = str(mapping.get("widget") or "")
        if not widget:
            continue
        if str(field_name) == EXPECTATION_STATUS_FIELD:
            value = normalize_expectation_status_value(value)
        payload[widget] = {"value": value}
    lookup_widget = str(((form_config.get("lookup_customer") or {}) if isinstance(form_config, dict) else {}).get("widget") or "")
    company_id = str(tool_input.get("company_id") or "")
    if lookup_widget and company_id:
        payload[lookup_widget] = {"value": company_id}
    customer_com_id = str(tool_input.get("customer_com_id") or tool_input.get("com_id") or "").strip()
    customer_com_name = str(
        tool_input.get("customer_com_name")
        or tool_input.get("customer_name")
        or tool_input.get("com_name")
        or ""
    ).strip()
    if target_form == "预期表":
        if customer_com_id:
            payload.setdefault("com_id", {"value": customer_com_id})
        if customer_com_name:
            payload.setdefault("com_name", {"value": customer_com_name})
    elif target_form == "场景表":
        if customer_com_id:
            payload.setdefault("com_id", {"value": customer_com_id})
        name_widget = _scene_customer_name_widget(form_config if isinstance(form_config, dict) else {})
        if customer_com_name and name_widget:
            payload.setdefault(name_widget, {"value": customer_com_name})
        lookup_yuqi_widget = str(((form_config.get("lookup_yuqi") or {}) if isinstance(form_config, dict) else {}).get("widget") or "_widget_1751435602563")
        related_yuqi_id = str(tool_input.get("related_yuqi_id") or "").strip()
        if related_yuqi_id and lookup_yuqi_widget:
            payload.setdefault(lookup_yuqi_widget, {"value": related_yuqi_id})
    return payload


def build_preview_text(tool_name: str, tool_input: dict[str, Any]) -> str:
    target_form = str(tool_input.get("target_form") or "未知表单")
    if tool_name == "create_customer_record":
        return f"准备新增到 {target_form}，字段数 {len((tool_input.get('fields') or {}).keys())}"
    if tool_name == "update_customer_record":
        return f"准备修改 {target_form} 记录 {tool_input.get('data_id')}"
    if tool_name == "delete_customer_record":
        return f"准备删除 {target_form} 记录 {tool_input.get('data_id')}"
    return "操作已准备好，等待用户确认执行"


def log_operation(
    db: Session,
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    status: str,
    source: str = "chat",
    jiandaoyun_response: dict[str, Any] | None = None,
    error: str | None = None,
    operator_name: str | None = None,
    operator_id: str | None = None,
) -> None:
    db.add(
        OperationLog(
            transcript_id=None,
            operation_type=f"{source}.{tool_name}",
            request_payload=tool_input,
            response_payload={"jiandaoyun_response": jiandaoyun_response, "error": error},
            status=status,
            operator_name=operator_name,
            operator_id=operator_id,
        )
    )
    db.commit()

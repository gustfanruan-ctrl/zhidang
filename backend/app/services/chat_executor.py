from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import OperationLog

OP_LABELS: dict[str, str] = {
    "create_customer_record": "新增",
    "update_customer_record": "修改",
    "delete_customer_record": "删除",
}


def get_entry_id(target_form: str, mapping_forms: dict[str, Any]) -> str:
    form_cfg = (mapping_forms or {}).get(target_form, {}) or {}
    return str(form_cfg.get("entry_id") or "")


def build_jiandaoyun_payload(tool_input: dict[str, Any], form_config: dict[str, Any]) -> dict[str, Any]:
    fields = tool_input.get("fields", {}) or {}
    field_mapping = (form_config.get("field_mapping") or {}) if isinstance(form_config, dict) else {}
    payload: dict[str, Any] = {}
    for field_name, value in fields.items():
        mapping = field_mapping.get(str(field_name), {}) or {}
        widget = str(mapping.get("widget") or "")
        if not widget:
            continue
        payload[widget] = {"value": value}
    lookup_widget = str(((form_config.get("lookup_customer") or {}) if isinstance(form_config, dict) else {}).get("widget") or "")
    company_id = str(tool_input.get("company_id") or "")
    if lookup_widget and company_id:
        payload[lookup_widget] = {"value": company_id}
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

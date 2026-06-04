from __future__ import annotations

from typing import Any

DEFAULT_FOLLOWUP_YUQI_LOOKUP_WIDGET = "_widget_1757576851901"
DEFAULT_FOLLOWUP_YUQI_TEXT_WIDGET = "review_yuqi_id"


def _lookup_name(cfg: Any) -> str:
    if isinstance(cfg, dict):
        return str(cfg.get("widget") or "").strip()
    if isinstance(cfg, str):
        return cfg.strip()
    return ""


def get_followup_form_cfg(field_mappings: dict[str, Any] | None) -> dict[str, Any]:
    root = dict(field_mappings or {})
    jiandaoyun = dict(root.get("jiandaoyun") or {})
    forms = dict(jiandaoyun.get("forms") or {})
    form_cfg = forms.get("跟进记录") or forms.get("跟进记录表") or {}
    return dict(form_cfg or {})


def get_followup_yuqi_widgets(field_mappings: dict[str, Any] | None) -> tuple[str, str]:
    form_cfg = get_followup_form_cfg(field_mappings)
    lookup_widget = _lookup_name(form_cfg.get("lookup_yuqi")) or DEFAULT_FOLLOWUP_YUQI_LOOKUP_WIDGET
    text_widget = str(form_cfg.get("yuqi_id_widget") or DEFAULT_FOLLOWUP_YUQI_TEXT_WIDGET).strip()
    return lookup_widget, text_widget


def apply_followup_yuqi_fields(
    payload: dict[str, Any],
    *,
    field_mappings: dict[str, Any] | None,
    yuqi_id: str | None,
) -> str:
    normalized = str(yuqi_id or "").strip()
    if not normalized:
        return ""
    lookup_widget, text_widget = get_followup_yuqi_widgets(field_mappings)
    if text_widget:
        payload[text_widget] = {"value": normalized}
    if lookup_widget:
        payload[lookup_widget] = {"value": normalized}
    return normalized


def _extract_lookup_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("value", "id", "_id", "data_id"):
            nested = value.get(key)
            if nested:
                return str(nested).strip()
        return ""
    if isinstance(value, list):
        for item in value:
            nested = _extract_lookup_value(item)
            if nested:
                return nested
    return ""


def extract_followup_yuqi_id(
    row: dict[str, Any] | None,
    *,
    field_mappings: dict[str, Any] | None = None,
) -> str:
    raw = dict(row or {})
    if not raw:
        return ""
    lookup_widget, text_widget = get_followup_yuqi_widgets(field_mappings)
    for key in ("yuqi_id", text_widget, lookup_widget):
        value = _extract_lookup_value(raw.get(key))
        if value:
            return value
    return ""

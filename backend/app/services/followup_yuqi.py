from __future__ import annotations

from typing import Any

DEFAULT_FOLLOWUP_YUQI_LOOKUP_WIDGET = "_widget_1757576851901"
DEFAULT_FOLLOWUP_YUQI_TEXT_WIDGET = "review_yuqi_id"
DEFAULT_FOLLOWUP_YUQI_SUBFORM_WIDGET = "_widget_1780904531626"
DEFAULT_FOLLOWUP_YUQI_LINK_WIDGET = "_widget_1780974773924"
DEFAULT_FOLLOWUP_YUQI_STAKEHOLDER_WIDGET = "_widget_1780974773919"
DEFAULT_FOLLOWUP_YUQI_BRIEF_WIDGET = "_widget_1780974773920"
DEFAULT_FOLLOWUP_YUQI_DETAIL_WIDGET = "_widget_1780974773921"
DEFAULT_FOLLOWUP_YUQI_STATUS_WIDGET = "_widget_1780974773922"
DEFAULT_FOLLOWUP_YUQI_UUID_WIDGET = "_widget_1780997127334"
DEFAULT_FOLLOWUP_YUQI_CONCAT_WIDGET = "yuqi_id_concat"


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


def get_followup_yuqi_subform_widgets(field_mappings: dict[str, Any] | None) -> dict[str, str]:
    form_cfg = get_followup_form_cfg(field_mappings)
    subform_cfg = dict(form_cfg.get("yuqi_subform") or {})
    return {
        "subform": str(subform_cfg.get("widget") or DEFAULT_FOLLOWUP_YUQI_SUBFORM_WIDGET).strip(),
        "link": str(subform_cfg.get("link_widget") or DEFAULT_FOLLOWUP_YUQI_LINK_WIDGET).strip(),
        "stakeholder": str(subform_cfg.get("stakeholder_widget") or DEFAULT_FOLLOWUP_YUQI_STAKEHOLDER_WIDGET).strip(),
        "brief": str(subform_cfg.get("brief_widget") or DEFAULT_FOLLOWUP_YUQI_BRIEF_WIDGET).strip(),
        "detail": str(subform_cfg.get("detail_widget") or DEFAULT_FOLLOWUP_YUQI_DETAIL_WIDGET).strip(),
        "status": str(subform_cfg.get("status_widget") or DEFAULT_FOLLOWUP_YUQI_STATUS_WIDGET).strip(),
        "uuid": str(subform_cfg.get("uuid_widget") or DEFAULT_FOLLOWUP_YUQI_UUID_WIDGET).strip(),
        "concat": str(subform_cfg.get("concat_widget") or DEFAULT_FOLLOWUP_YUQI_CONCAT_WIDGET).strip(),
    }


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("value", "name", "label", "text", "id", "_id"):
            nested = value.get(key)
            if nested:
                return str(nested).strip()
        return ""
    if isinstance(value, list):
        return "，".join(_text(item) for item in value if _text(item))
    return str(value).strip()


def build_followup_yuqi_subform_row(
    *,
    yuqi_data_id: str,
    yuqi_record: dict[str, Any] | None = None,
    field_mappings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    widgets = get_followup_yuqi_subform_widgets(field_mappings)
    row: dict[str, Any] = {}
    normalized_id = str(yuqi_data_id or "").strip()
    record = dict(yuqi_record or {})
    if widgets["link"] and normalized_id:
        row[widgets["link"]] = {"value": {"id": normalized_id}}
    if widgets["stakeholder"]:
        row[widgets["stakeholder"]] = {"value": _text(record.get("cont_name_array"))}
    if widgets["brief"]:
        row[widgets["brief"]] = {"value": _text(record.get("detail_brief"))}
    if widgets["detail"]:
        row[widgets["detail"]] = {"value": _text(record.get("detail"))}
    if widgets["status"]:
        row[widgets["status"]] = {"value": _text(record.get("yuqi_status"))}
    if widgets["uuid"]:
        row[widgets["uuid"]] = {"value": _text(record.get("yuqi_id"))}
    return row


def apply_followup_yuqi_fields(
    payload: dict[str, Any],
    *,
    field_mappings: dict[str, Any] | None,
    yuqi_id: str | None,
    yuqi_record: dict[str, Any] | None = None,
) -> str:
    normalized = str(yuqi_id or "").strip()
    if not normalized:
        return ""
    widgets = get_followup_yuqi_subform_widgets(field_mappings)
    row = build_followup_yuqi_subform_row(
        yuqi_data_id=normalized,
        yuqi_record=yuqi_record,
        field_mappings=field_mappings,
    )
    if widgets["subform"] and row:
        payload[widgets["subform"]] = {"value": [row]}
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
    widgets = get_followup_yuqi_subform_widgets(field_mappings)
    subform_rows = raw.get(widgets["subform"])
    if isinstance(subform_rows, list):
        for subrow in subform_rows:
            if not isinstance(subrow, dict):
                continue
            link_value = subrow.get(widgets["link"])
            if isinstance(link_value, dict) and link_value.get("id"):
                return str(link_value.get("id") or "").strip()
            value = _extract_lookup_value(link_value)
            if value:
                return value
    concat_value = _extract_lookup_value(raw.get(widgets["concat"]))
    if concat_value:
        return concat_value
    lookup_widget, text_widget = get_followup_yuqi_widgets(field_mappings)
    for key in ("yuqi_id", text_widget, lookup_widget):
        value = _extract_lookup_value(raw.get(key))
        if value:
            return value
    return ""

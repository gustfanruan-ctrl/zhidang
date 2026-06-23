from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models import OperationCardLog
from .jiandaoyun_writer import JiandaoyunWriter

MAX_LOG_WIDGET_NAME_LEN = 100


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _wrap_value(value: Any) -> dict[str, Any]:
    return {"value": value}


def _extract_response_data_id(resp: dict[str, Any]) -> str:
    for key in ("data_id", "_id"):
        value = resp.get(key)
        if value:
            return str(value)
    data = resp.get("data")
    if isinstance(data, dict):
        for key in ("data_id", "_id"):
            value = data.get(key)
            if value:
                return str(value)
    return ""


def _extract_record_value(resp: dict[str, Any], widget_name: str) -> str:
    data = resp.get("data")
    if not isinstance(data, dict):
        data = resp
    value = data.get(widget_name) if isinstance(data, dict) else None
    if isinstance(value, dict):
        value = value.get("value")
    return str(value or "").strip()


def _scene_customer_name_widget(form_cfg: dict[str, Any]) -> str:
    configured = form_cfg.get("customer_name_widget") or form_cfg.get("customer_name_helper")
    if isinstance(configured, dict):
        return str(configured.get("widget") or "")
    if isinstance(configured, str):
        return configured
    return "_widget_1743993204408"


def _build_log_widget_name(change_items: list[dict[str, Any]], fallback_widget_name: str = "") -> str:
    widgets: list[str] = []
    seen: set[str] = set()
    for item in change_items:
        widget = str(item.get("widget_name") or "").strip()
        if not widget or widget in seen:
            continue
        seen.add(widget)
        widgets.append(widget)
    if not widgets and fallback_widget_name:
        fallback = str(fallback_widget_name or "").strip()
        if fallback:
            widgets.append(fallback)
    if not widgets:
        return ""

    joined = ",".join(widgets)
    if len(joined) <= MAX_LOG_WIDGET_NAME_LEN:
        return joined

    kept: list[str] = []
    for idx, widget in enumerate(widgets):
        remaining = len(widgets) - idx - 1
        suffix = f",...(+{remaining})" if remaining > 0 else ""
        candidate = ",".join(kept + [widget]) + suffix
        if len(candidate) > MAX_LOG_WIDGET_NAME_LEN:
            break
        kept.append(widget)

    if kept:
        remaining = len(widgets) - len(kept)
        return ",".join(kept) if remaining <= 0 else f"{','.join(kept)},...(+{remaining})"

    suffix = ",...(+1)"
    limit = max(1, MAX_LOG_WIDGET_NAME_LEN - len(suffix))
    return f"{widgets[0][:limit]}{suffix}"


async def execute_cards(
    *,
    db: Session,
    transcript_id: str,
    cards: list[dict[str, Any]],
    writer: JiandaoyunWriter,
    mapping_forms: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    indexed_cards = list(enumerate(cards))
    indexed_cards.sort(key=lambda pair: (0 if str(pair[1].get("target_form") or "") == "预期表" else 1, pair[0]))
    cards_by_id = {str(card.get("card_id") or ""): card for card in cards if card.get("card_id")}
    resolved_data_ids = {
        str(card.get("card_id") or ""): str(card.get("data_id") or "")
        for card in cards
        if card.get("card_id") and card.get("data_id")
    }
    resolved_business_ids: dict[str, str] = {}
    expectation_form_cfg = mapping_forms.get("预期表", {})
    expectation_entry_id = str(expectation_form_cfg.get("entry_id") or "")
    expectation_business_id_widget = str(expectation_form_cfg.get("business_id_widget") or "yuqi_id")

    async def resolve_expectation_business_id(data_id: str) -> str:
        normalized_data_id = str(data_id or "").strip()
        if not normalized_data_id or not expectation_entry_id:
            return ""
        cached = resolved_business_ids.get(normalized_data_id)
        if cached:
            return cached
        read_resp = await writer.read_record(expectation_entry_id, normalized_data_id)
        if not read_resp.get("success"):
            return ""
        business_id = _extract_record_value(read_resp, expectation_business_id_widget)
        if not business_id:
            business_id = str(uuid4())
            update_resp = await writer.update_record(
                expectation_entry_id,
                normalized_data_id,
                {expectation_business_id_widget: _wrap_value(business_id)},
            )
            if not update_resp.get("success"):
                return ""
        resolved_business_ids[normalized_data_id] = business_id
        return business_id

    for idx, card in indexed_cards:
        card_id = str(card.get("card_id") or uuid4())
        target_form = str(card.get("target_form") or "未知")
        op_type = str(card.get("operation_type") or "update")
        widget_name = str(card.get("widget_name") or "")
        data_id = str(card.get("data_id") or "")
        safety_status = str(card.get("safety_status") or "unknown")
        form_cfg = mapping_forms.get(target_form, {})
        entry_id = str(form_cfg.get("entry_id") or "")
        change_items = list(card.get("change_items") or [])
        if not change_items and card.get("field_name"):
            change_items = [
                {
                    "field_name": card.get("field_name"),
                    "widget_name": card.get("widget_name"),
                    "old_value": card.get("old_value"),
                    "new_value": card.get("new_value"),
                }
            ]
        log_widget_name = _build_log_widget_name(change_items, widget_name)
        execute_status = "pending"
        resp: dict[str, Any] = {}
        if op_type == "skip":
            execute_status = "skipped"
            resp = {"success": True, "detail": "skipped by approved operation type"}
            db.add(
                OperationCardLog(
                    transcript_id=transcript_id,
                    card_index=idx,
                    target_form=target_form,
                    operation_type=op_type,
                    widget_name=log_widget_name,
                    old_value=str([{ "field_name": item.get("field_name"), "old_value": item.get("old_value")} for item in change_items]) if change_items else None,
                    new_value=str([{ "field_name": item.get("field_name"), "new_value": item.get("new_value")} for item in change_items]) if change_items else None,
                    safety_status=safety_status,
                    execute_status=execute_status,
                    jiandaoyun_response=resp,
                    executed_at=now_utc(),
                )
            )
            db.commit()
            results.append({"card_id": card_id, "execute_status": execute_status, "error": None})
            continue
        if safety_status in {"rejected", "forbidden"}:
            execute_status = "skipped"
            resp = {"success": False, "detail": "blocked by safety check"}
        elif not entry_id:
            execute_status = "failed"
            resp = {"success": False, "detail": f"missing entry_id for form: {target_form}"}
        else:
            payload: dict[str, Any] = {}
            for item in change_items:
                item_widget = str(item.get("widget_name") or "")
                if not item_widget:
                    continue
                payload[item_widget] = _wrap_value(item.get("new_value"))
            if not payload and op_type != "append_subform":
                execute_status = "skipped"
                resp = {"success": False, "detail": "no writable change fields"}
                db.add(
                    OperationCardLog(
                        transcript_id=transcript_id,
                        card_index=idx,
                        target_form=target_form,
                        operation_type=op_type,
                        widget_name="",
                        old_value=None,
                        new_value=None,
                        safety_status=safety_status,
                        execute_status=execute_status,
                        jiandaoyun_response=resp,
                        executed_at=now_utc(),
                    )
                )
                db.commit()
                results.append({"card_id": card_id, "execute_status": execute_status, "error": resp.get("detail")})
                continue
            if op_type == "create":
                lookup_widget = str(card.get("lookup_widget") or "")
                customer_id = str(card.get("customer_id") or "")
                # For new yuqi/changjing records, auto-link to customer main record.
                if lookup_widget and customer_id and target_form in {"预期表", "场景表"}:
                    payload[lookup_widget] = _wrap_value(customer_id)
                    if target_form == "预期表":
                        customer_com_id = str(card.get("customer_com_id") or "").strip()
                        customer_com_name = str(card.get("customer_com_name") or card.get("customer_name") or "").strip()
                        if customer_com_id:
                            payload.setdefault("com_id", _wrap_value(customer_com_id))
                        if customer_com_name:
                            payload.setdefault("com_name", _wrap_value(customer_com_name))
                elif target_form in {"预期表", "场景表"} and lookup_widget and not customer_id:
                    execute_status = "failed"
                    resp = {"success": False, "detail": "missing customer_id for lookup relation"}
                    db.add(
                        OperationCardLog(
                        transcript_id=transcript_id,
                        card_index=idx,
                        target_form=target_form,
                        operation_type=op_type,
                        widget_name=log_widget_name,
                        old_value=str([{ "field_name": item.get("field_name"), "old_value": item.get("old_value")} for item in change_items]),
                        new_value=str([{ "field_name": item.get("field_name"), "new_value": item.get("new_value")} for item in change_items]),
                        safety_status=safety_status,
                        execute_status=execute_status,
                            jiandaoyun_response=resp,
                            executed_at=now_utc(),
                        )
                    )
                    db.commit()
                    results.append({"card_id": card_id, "execute_status": execute_status, "error": resp.get("detail")})
                    continue
                if (
                    target_form == "预期表"
                    and expectation_business_id_widget
                    and not _extract_record_value(
                        {"data": payload},
                        expectation_business_id_widget,
                    )
                ):
                    payload[expectation_business_id_widget] = _wrap_value(str(uuid4()))

            if target_form == "场景表":
                customer_com_id = str(card.get("customer_com_id") or "").strip()
                customer_com_name = str(card.get("customer_com_name") or card.get("customer_name") or "").strip()
                if customer_com_id:
                    payload.setdefault("com_id", _wrap_value(customer_com_id))
                name_widget = _scene_customer_name_widget(form_cfg)
                if customer_com_name and name_widget:
                    payload.setdefault(name_widget, _wrap_value(customer_com_name))

                related_yuqi_id = str(card.get("related_yuqi_id") or "").strip()
                related_card_id = str(card.get("related_yuqi_card_id") or "").strip()
                if related_card_id:
                    related_yuqi_id = resolved_data_ids.get(related_card_id) or str((cards_by_id.get(related_card_id) or {}).get("data_id") or "").strip()
                    if not related_yuqi_id:
                        execute_status = "failed"
                        resp = {"success": False, "detail": f"related expectation card not executed: {related_card_id}"}
                        db.add(
                            OperationCardLog(
                                transcript_id=transcript_id,
                                card_index=idx,
                                target_form=target_form,
                                operation_type=op_type,
                                widget_name=log_widget_name,
                                old_value=str([{ "field_name": item.get("field_name"), "old_value": item.get("old_value")} for item in change_items]),
                                new_value=str([{ "field_name": item.get("field_name"), "new_value": item.get("new_value")} for item in change_items]),
                                safety_status=safety_status,
                                execute_status=execute_status,
                                jiandaoyun_response=resp,
                                executed_at=now_utc(),
                            )
                        )
                        db.commit()
                        results.append({"card_id": card_id, "execute_status": execute_status, "error": resp.get("detail")})
                        continue
                    card["related_yuqi_id"] = related_yuqi_id

                lookup_yuqi_widget = str((form_cfg.get("lookup_yuqi") or {}).get("widget") or "_widget_1751435602563")
                if related_yuqi_id and lookup_yuqi_widget:
                    payload.setdefault(lookup_yuqi_widget, _wrap_value(related_yuqi_id))
                    related_business_id = ""
                    if related_card_id:
                        related_business_id = resolved_business_ids.get(related_card_id, "")
                    if not related_business_id:
                        related_business_id = await resolve_expectation_business_id(related_yuqi_id)
                    related_business_id_widget = str(
                        form_cfg.get("related_business_id_widget") or "expect_id"
                    )
                    if not related_business_id:
                        execute_status = "failed"
                        resp = {
                            "success": False,
                            "detail": f"failed to resolve expectation business id: {related_yuqi_id}",
                        }
                        db.add(
                            OperationCardLog(
                                transcript_id=transcript_id,
                                card_index=idx,
                                target_form=target_form,
                                operation_type=op_type,
                                widget_name=log_widget_name,
                                old_value=str(
                                    [
                                        {
                                            "field_name": item.get("field_name"),
                                            "old_value": item.get("old_value"),
                                        }
                                        for item in change_items
                                    ]
                                ),
                                new_value=str(
                                    [
                                        {
                                            "field_name": item.get("field_name"),
                                            "new_value": item.get("new_value"),
                                        }
                                        for item in change_items
                                    ]
                                ),
                                safety_status=safety_status,
                                execute_status=execute_status,
                                jiandaoyun_response=resp,
                                executed_at=now_utc(),
                            )
                        )
                        db.commit()
                        results.append(
                            {
                                "card_id": card_id,
                                "execute_status": execute_status,
                                "error": resp.get("detail"),
                            }
                        )
                        continue
                    if related_business_id_widget:
                        payload[related_business_id_widget] = _wrap_value(related_business_id)

            if op_type == "create":
                resp = await writer.create_record(entry_id, payload)
            elif op_type == "append_subform":
                subform_rows = card.get("new_rows", [])
                resp = await writer.update_subform_append(entry_id, data_id, widget_name, subform_rows)
            else:
                resp = await writer.update_record(entry_id, data_id, payload)
            execute_status = "success" if resp.get("success") else "failed"
            if execute_status == "success":
                resolved_id = _extract_response_data_id(resp) or data_id
                if resolved_id:
                    resolved_data_ids[card_id] = resolved_id
                    card["data_id"] = resolved_id
                    if target_form == "预期表":
                        business_id = _extract_record_value(
                            {"data": payload},
                            expectation_business_id_widget,
                        )
                        if business_id:
                            resolved_business_ids[card_id] = business_id
                            resolved_business_ids[resolved_id] = business_id

        db.add(
            OperationCardLog(
                transcript_id=transcript_id,
                card_index=idx,
                target_form=target_form,
                operation_type=op_type,
                widget_name=log_widget_name,
                old_value=str([{ "field_name": item.get("field_name"), "old_value": item.get("old_value")} for item in change_items]) if change_items else (None if card.get("old_value") is None else str(card.get("old_value"))),
                new_value=str([{ "field_name": item.get("field_name"), "new_value": item.get("new_value")} for item in change_items]) if change_items else (None if card.get("new_value") is None else str(card.get("new_value"))),
                safety_status=safety_status,
                execute_status=execute_status,
                jiandaoyun_response=resp,
                executed_at=now_utc(),
            )
        )
        db.commit()
        results.append({"card_id": card_id, "execute_status": execute_status, "error": None if execute_status == "success" else resp.get("detail")})
    return results

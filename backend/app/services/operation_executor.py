from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models import OperationCardLog
from .jiandaoyun_writer import JiandaoyunWriter


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _wrap_value(value: Any) -> dict[str, Any]:
    return {"value": value}


async def execute_cards(
    *,
    db: Session,
    transcript_id: str,
    cards: list[dict[str, Any]],
    writer: JiandaoyunWriter,
    mapping_forms: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for idx, card in enumerate(cards):
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
        execute_status = "pending"
        resp: dict[str, Any] = {}
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
                elif target_form in {"预期表", "场景表"} and lookup_widget and not customer_id:
                    execute_status = "failed"
                    resp = {"success": False, "detail": "missing customer_id for lookup relation"}
                    db.add(
                        OperationCardLog(
                            transcript_id=transcript_id,
                            card_index=idx,
                            target_form=target_form,
                            operation_type=op_type,
                            widget_name=",".join(str(item.get("widget_name") or "") for item in change_items if item.get("widget_name")),
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
                resp = await writer.create_record(entry_id, payload)
            elif op_type == "append_subform":
                subform_rows = card.get("new_rows", [])
                resp = await writer.update_subform_append(entry_id, data_id, widget_name, subform_rows)
            else:
                resp = await writer.update_record(entry_id, data_id, payload)
            execute_status = "success" if resp.get("success") else "failed"

        db.add(
            OperationCardLog(
                transcript_id=transcript_id,
                card_index=idx,
                target_form=target_form,
                operation_type=op_type,
                widget_name=",".join(str(item.get("widget_name") or "") for item in change_items if item.get("widget_name")) or widget_name,
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

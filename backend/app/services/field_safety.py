from __future__ import annotations

from typing import Any


def check_operation_cards(cards: list[dict[str, Any]], form_config: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = form_config.get("field_mapping", {}) or {}
    forbidden = set(form_config.get("forbidden_fields", []) or [])
    result: list[dict[str, Any]] = []

    for card in cards:
        updated = dict(card)
        change_items = list(card.get("change_items") or [])
        # Backward compatibility: legacy single-field card
        if not change_items and card.get("field_name"):
            change_items = [
                {
                    "field_name": card.get("field_name"),
                    "widget_name": card.get("widget_name"),
                    "new_value": card.get("new_value"),
                }
            ]

        if not change_items:
            updated["safety_status"] = "rejected"
            updated["safety_reason"] = "no change_items"
            result.append(updated)
            continue

        item_results: list[dict[str, Any]] = []
        aggregate_status = "writable"
        aggregate_reason = "all fields writable"
        for item in change_items:
            field_name = str(item.get("field_name", "")).strip()
            widget_name = str(item.get("widget_name", "")).strip()
            new_value = item.get("new_value")
            rule = mapping.get(field_name, {})
            widget = str(rule.get("widget", "")) or widget_name

            item_status = "writable"
            item_reason = "field is writable"
            if widget in forbidden or field_name in forbidden:
                item_status = "rejected"
                item_reason = "field is forbidden"
            else:
                safety = str(rule.get("safety", "writable"))
                if safety == "restricted":
                    allowed = rule.get("allowed_values", []) or []
                    if allowed and str(new_value) not in set(str(i) for i in allowed):
                        item_status = "rejected"
                        item_reason = "value is not in allowed_values"
                    else:
                        item_status = "restricted"
                        item_reason = "requires restricted value validation"
                elif safety == "forbidden":
                    item_status = "rejected"
                    item_reason = "field safety is forbidden"
            if item_status == "rejected":
                aggregate_status = "rejected"
                aggregate_reason = f"{field_name or widget_name}: {item_reason}"
            elif item_status == "restricted" and aggregate_status != "rejected":
                aggregate_status = "restricted"
                aggregate_reason = "contains restricted fields"
            item_results.append({**item, "safety_status": item_status, "safety_reason": item_reason})

        updated["change_items"] = item_results
        updated["safety_status"] = aggregate_status
        updated["safety_reason"] = aggregate_reason
        result.append(updated)
    return result


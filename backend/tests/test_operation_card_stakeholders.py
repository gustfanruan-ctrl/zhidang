import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import _apply_operation_card_field_updates, _apply_operation_card_override  # noqa: E402


def test_expectation_card_stakeholder_override_appends_writable_fields_without_runtime_mapping():
    card = {
        "card_id": "card-1",
        "target_form": "预期表",
        "change_items": [
            {"field_name": "预期简述", "widget_name": "detail_brief", "new_value": "原预期"}
        ],
    }
    override = {
        "target_form": "预期表",
        "stakeholder_contacts": [
            {"cont_id": "c-1", "cont_name": "张三"},
            {"cont_id": "c-2", "cont_name": "李四"},
        ],
        "stakeholder_contacts_touched": True,
    }

    _apply_operation_card_override(card, override, {"预期表": {}})
    changed = _apply_operation_card_field_updates(card, {}, {"预期表": {}})

    assert changed is True
    by_field = {item["field_name"]: item for item in card["change_items"]}
    assert by_field["关联干系人"]["widget_name"] == "cont_name_array"
    assert by_field["关联干系人"]["new_value"] == "张三，李四"
    assert by_field["干系人id"]["widget_name"] == "cont_id"
    assert by_field["干系人id"]["new_value"] == "c-1,c-2"


def test_non_expectation_card_drops_stakeholder_override():
    card = {"card_id": "card-2", "target_form": "场景表", "change_items": []}

    _apply_operation_card_override(
        card,
        {
            "target_form": "场景表",
            "stakeholder_contact_names": "张三",
            "stakeholder_contact_ids": "c-1",
            "stakeholder_contacts_touched": True,
        },
        {"场景表": {}},
    )
    changed = _apply_operation_card_field_updates(card, {}, {"场景表": {}})

    assert changed is False
    assert "stakeholder_contact_names" not in card
    assert "stakeholder_contact_ids" not in card

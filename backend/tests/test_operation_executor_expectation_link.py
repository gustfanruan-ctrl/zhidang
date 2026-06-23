from __future__ import annotations

from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from backend.app.services.operation_executor import execute_cards


MAPPING_FORMS = {
    "预期表": {
        "entry_id": "expectation-entry",
        "business_id_widget": "yuqi_id",
    },
    "场景表": {
        "entry_id": "scene-entry",
        "lookup_yuqi": {"widget": "_widget_1751435602563"},
        "related_business_id_widget": "expect_id",
    },
}


def _change(widget: str, value: str) -> dict[str, str]:
    return {
        "field_name": widget,
        "widget_name": widget,
        "old_value": "",
        "new_value": value,
    }


def _db() -> Mock:
    db = Mock()
    db.add = Mock()
    db.commit = Mock()
    return db


@pytest.mark.asyncio
async def test_new_expectation_and_scene_share_generated_business_id():
    writer = Mock()
    writer.create_record = AsyncMock(
        side_effect=[
            {"success": True, "data_id": "expectation-row-1"},
            {"success": True, "data_id": "scene-row-1"},
        ]
    )
    writer.update_record = AsyncMock()
    writer.read_record = AsyncMock()
    cards = [
        {
            "card_id": "scene-card",
            "target_form": "场景表",
            "operation_type": "create",
            "safety_status": "writable",
            "related_yuqi_card_id": "expectation-card",
            "change_items": [
                _change("title", "scene"),
                _change("expect_id", ""),
            ],
        },
        {
            "card_id": "expectation-card",
            "target_form": "预期表",
            "operation_type": "create",
            "safety_status": "writable",
            "change_items": [
                _change("detail_brief", "expectation"),
                _change("yuqi_id", ""),
            ],
        },
    ]

    results = await execute_cards(
        db=_db(),
        transcript_id="transcript-1",
        cards=cards,
        writer=writer,
        mapping_forms=MAPPING_FORMS,
    )

    expectation_payload = writer.create_record.await_args_list[0].args[1]
    scene_payload = writer.create_record.await_args_list[1].args[1]
    business_id = expectation_payload["yuqi_id"]["value"]
    UUID(business_id)
    assert scene_payload["_widget_1751435602563"] == {"value": "expectation-row-1"}
    assert scene_payload["expect_id"] == {"value": business_id}
    assert [item["execute_status"] for item in results] == ["success", "success"]
    writer.read_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_expectation_business_id_is_copied_to_scene():
    writer = Mock()
    writer.create_record = AsyncMock(return_value={"success": True, "data_id": "scene-row-1"})
    writer.update_record = AsyncMock()
    writer.read_record = AsyncMock(
        return_value={"success": True, "data": {"yuqi_id": "business-id-1"}}
    )
    card = {
        "card_id": "scene-card",
        "target_form": "场景表",
        "operation_type": "create",
        "safety_status": "writable",
        "related_yuqi_id": "expectation-row-1",
        "change_items": [_change("title", "scene")],
    }

    results = await execute_cards(
        db=_db(),
        transcript_id="transcript-1",
        cards=[card],
        writer=writer,
        mapping_forms=MAPPING_FORMS,
    )

    payload = writer.create_record.await_args.args[1]
    assert payload["_widget_1751435602563"] == {"value": "expectation-row-1"}
    assert payload["expect_id"] == {"value": "business-id-1"}
    assert results[0]["execute_status"] == "success"
    writer.update_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_existing_expectation_business_id_is_backfilled():
    writer = Mock()
    writer.create_record = AsyncMock(return_value={"success": True, "data_id": "scene-row-1"})
    writer.update_record = AsyncMock(return_value={"success": True})
    writer.read_record = AsyncMock(return_value={"success": True, "data": {"yuqi_id": ""}})
    card = {
        "card_id": "scene-card",
        "target_form": "场景表",
        "operation_type": "create",
        "safety_status": "writable",
        "related_yuqi_id": "expectation-row-1",
        "change_items": [_change("title", "scene")],
    }

    results = await execute_cards(
        db=_db(),
        transcript_id="transcript-1",
        cards=[card],
        writer=writer,
        mapping_forms=MAPPING_FORMS,
    )

    backfill_payload = writer.update_record.await_args.args[2]
    scene_payload = writer.create_record.await_args.args[1]
    generated_id = backfill_payload["yuqi_id"]["value"]
    UUID(generated_id)
    assert scene_payload["expect_id"] == {"value": generated_id}
    assert results[0]["execute_status"] == "success"

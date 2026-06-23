from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from backend.app import main
from backend.app.models import FollowupRecord, Transcript
from backend.app.schemas.operation import OperationTypeCalibrationRequest
from backend.app.services.operation_executor import execute_cards


def test_calibration_tracks_original_type_and_clears_marker_when_restored():
    card = {"card_id": "card-1", "operation_type": "update", "data_id": "existing-1"}

    previous, current = main._calibrate_operation_card_type(card, "create")

    assert (previous, current) == ("update", "create")
    assert card["original_operation_type"] == "update"
    assert card["operation_type_calibrated"] is True
    assert card["data_id"] == "existing-1"

    main._calibrate_operation_card_type(card, "update")

    assert card["operation_type"] == "update"
    assert card["original_operation_type"] == "update"
    assert card["operation_type_calibrated"] is False


def test_calibration_rejects_update_without_matched_record():
    card = {"card_id": "card-1", "operation_type": "create"}

    with pytest.raises(ValueError, match="没有匹配记录"):
        main._calibrate_operation_card_type(card, "update")


@pytest.mark.parametrize("record_type", [Transcript, FollowupRecord])
def test_calibration_route_persists_transcript_and_followup_cards(monkeypatch, record_type):
    record = record_type(
        id="record-1",
        source="upload" if record_type is Transcript else "jiandaoyun",
        raw_text="content",
        agent_b_result={
            "result": {
                "operation_cards": [
                    {"card_id": "card-1", "operation_type": "update", "data_id": "existing-1"}
                ]
            }
        },
    )
    cards = [
        {"card_id": "card-1", "operation_type": "update", "data_id": "existing-1"}
    ]
    db = Mock()
    audit = Mock()
    monkeypatch.setattr(main, "_get_allowed_operation_record", lambda *_args: record)
    monkeypatch.setattr(main, "_restore_operation_cards_from_db", lambda *_args: cards)
    monkeypatch.setattr(main, "emit_event", audit)
    main.OPERATION_CARD_STORE.pop(record.id, None)

    response = main.calibrate_operation_type(
        record.id,
        "card-1",
        OperationTypeCalibrationRequest(operation_type="skip"),
        db=db,
        user={"username": "reviewer", "source": "user"},
    )

    persisted = record.agent_b_result["result"]["operation_cards"][0]
    assert response["operation_type"] == "skip"
    assert response["operation_type_calibrated"] is True
    assert persisted["original_operation_type"] == "update"
    assert main.OPERATION_CARD_STORE[record.id][0]["operation_type"] == "skip"
    db.commit.assert_called_once()
    audit.assert_called_once()
    audit_payload = audit.call_args.args[4]
    assert audit_payload["previous_operation_type"] == "update"
    assert audit_payload["operation_type"] == "skip"


class _FailOnWrite:
    async def create_record(self, *_args, **_kwargs):
        raise AssertionError("skip must not call create_record")

    async def update_record(self, *_args, **_kwargs):
        raise AssertionError("skip must not call update_record")

    async def update_subform_append(self, *_args, **_kwargs):
        raise AssertionError("skip must not call update_subform_append")


@pytest.mark.asyncio
async def test_execute_skip_never_calls_jiandaoyun_writer():
    db = Mock()
    card = {
        "card_id": "card-1",
        "target_form": "预期表",
        "operation_type": "skip",
        "data_id": "existing-1",
        "safety_status": "writable",
        "change_items": [
            {
                "field_name": "预期简述",
                "widget_name": "detail_brief",
                "old_value": "old",
                "new_value": "new",
            }
        ],
    }

    results = await execute_cards(
        db=db,
        transcript_id="record-1",
        cards=[card],
        writer=_FailOnWrite(),
        mapping_forms={"预期表": {"entry_id": "entry-1"}},
    )

    assert results == [{"card_id": "card-1", "execute_status": "skipped", "error": None}]
    db.add.assert_called_once()
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_execute_create_and_update_keep_existing_writer_paths():
    db = Mock()
    writer = Mock()
    writer.create_record = AsyncMock(return_value={"success": True, "data_id": "created-1"})
    writer.update_record = AsyncMock(return_value={"success": True})
    writer.update_subform_append = AsyncMock(return_value={"success": True})
    base_item = {
        "field_name": "预期简述",
        "widget_name": "detail_brief",
        "old_value": "",
        "new_value": "new",
    }
    cards = [
        {
            "card_id": "create-card",
            "target_form": "预期表",
            "operation_type": "create",
            "customer_id": "customer-1",
            "lookup_widget": "customer_widget",
            "safety_status": "writable",
            "change_items": [dict(base_item)],
        },
        {
            "card_id": "update-card",
            "target_form": "预期表",
            "operation_type": "update",
            "data_id": "existing-1",
            "safety_status": "writable",
            "change_items": [dict(base_item)],
        },
    ]

    results = await execute_cards(
        db=db,
        transcript_id="record-1",
        cards=cards,
        writer=writer,
        mapping_forms={"预期表": {"entry_id": "entry-1"}},
    )

    assert [item["execute_status"] for item in results] == ["success", "success"]
    writer.create_record.assert_awaited_once()
    writer.update_record.assert_awaited_once_with(
        "entry-1",
        "existing-1",
        {"detail_brief": {"value": "new"}},
    )
    writer.update_subform_append.assert_not_awaited()


def test_frontend_exposes_immediate_operation_type_calibration():
    page = (Path(__file__).resolve().parents[2] / "frontend/src/pages/TranscriptsPage.vue").read_text(
        encoding="utf-8"
    )
    api = (Path(__file__).resolve().parents[2] / "frontend/src/api/operation.js").read_text(
        encoding="utf-8"
    )

    assert "calibrateCardOperationType" in page
    assert '<option v-if="item.dataId" value="update">更新</option>' in page
    assert "operationTypeCalibrated" in page
    assert "成功 ${ok}，跳过 ${skipped}，失败 ${fail}" in page
    assert "api.patch(" in api
    assert "/operation-type" in api

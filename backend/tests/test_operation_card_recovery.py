import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import (  # noqa: E402
    OPERATION_CARD_STORE,
    _resolve_requested_operation_cards,
    _restore_operation_cards_from_db,
)


def test_resolve_requested_operation_cards_falls_back_to_requested_ids_when_review_status_missing():
    cards = [
        {"card_id": "card-1", "target_form": "预期表"},
        {"card_id": "card-2", "target_form": "场景表", "review_status": "rejected"},
    ]

    approved = _resolve_requested_operation_cards(cards, {"card-1"})

    assert [card["card_id"] for card in approved] == ["card-1"]
    assert cards[0]["review_status"] == "approved"


def test_restore_operation_cards_from_db_loads_followup_record_and_populates_store():
    transcript_id = "followup-1"
    OPERATION_CARD_STORE.pop(transcript_id, None)
    record = SimpleNamespace(
        agent_b_result={
            "result": {
                "operation_cards": [
                    {"card_id": "card-a", "target_form": "预期表", "review_status": "approved"},
                ]
            }
        }
    )

    class DummyDb:
        def get(self, model, key):
            if key != transcript_id:
                return None
            return None if model.__name__ == "Transcript" else record

    restored = _restore_operation_cards_from_db(transcript_id, DummyDb())

    assert restored == [{"card_id": "card-a", "target_form": "预期表", "review_status": "approved"}]
    assert OPERATION_CARD_STORE[transcript_id] == restored


import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main as main_module  # noqa: E402
from app.services.followup_push import (  # noqa: E402
    build_followup_push_request,
    extract_created_data_id,
    get_followup_push_config,
)


def test_get_followup_push_config_defaults_to_enabled_and_default_url():
    cfg = get_followup_push_config({"jiandaoyun": {}})

    assert cfg["enabled"] is True
    assert cfg["url"] == "http://121.199.167.115:2220/dataway/service/success_chuchai"
    assert cfg["secret"] == ""


def test_build_followup_push_request_omits_signature_when_secret_missing():
    params, headers, body_text = build_followup_push_request({"op": "data_create", "data": {"review_id": "r-1"}})

    assert "timestamp" in params
    assert "nonce" in params
    assert headers["Content-Type"] == "application/json"
    assert "X-JDY-DeliverId" in headers
    assert "X-JDY-Signature" not in headers
    assert '"review_id":"r-1"' in body_text


def test_extract_created_data_id_supports_multiple_result_shapes():
    assert extract_created_data_id({"data_id": "d-1"}) == "d-1"
    assert extract_created_data_id({"_id": "d-2"}) == "d-2"
    assert extract_created_data_id({"data": {"_id": "d-3"}}) == "d-3"
    assert extract_created_data_id({"data": {"data_id": "d-4"}}) == "d-4"


@pytest.mark.asyncio
async def test_submit_review_pushes_to_travel_server_even_without_secret(monkeypatch):
    class DummyScalarResult:
        def __init__(self, cfg):
            self._cfg = cfg

        def first(self):
            return self._cfg

    class DummyDB:
        def __init__(self, cfg):
            self.cfg = cfg

        def scalars(self, _stmt):
            return DummyScalarResult(self.cfg)

        def add(self, _obj):
            pass

        def commit(self):
            pass

    cfg = SimpleNamespace(
        jiandaoyun_api_key_encrypted="encrypted",
        jiandaoyun_app_id="app-1",
        field_mappings={"jiandaoyun": {"followup_push": {"enabled": True}}},
    )
    db = DummyDB(cfg)

    class DummyWriter:
        def __init__(self, *args, **kwargs):
            pass

        async def create_record(self, entry_id, data):
            assert entry_id == "670a28334883adafb152a869"
            assert data["review_record"]["value"] == "本次完成现场跟进"
            return {"success": True, "data": {"_id": "row-1"}}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def query_single_data(self, app_id, entry_id, data_id):
            assert app_id == "app-1"
            assert entry_id == "670a28334883adafb152a869"
            assert data_id == "row-1"
            return {"data": {"_id": "row-1", "review_id": "review-1", "if_tuisong": "是"}}

    pushed = {}

    async def fake_push_followup_to_travel_server(*, url, payload, secret="", timeout_seconds=2.0):
        pushed["url"] = url
        pushed["payload"] = payload
        pushed["secret"] = secret
        pushed["timeout_seconds"] = timeout_seconds
        return {"ok": True, "status_code": 200, "response_text": "ok", "deliver_id": "deliver-1"}

    monkeypatch.setattr(main_module, "decrypt_secret", lambda value: "api-key")
    monkeypatch.setattr(main_module, "JiandaoyunWriter", DummyWriter)
    monkeypatch.setattr(main_module, "JiandaoyunClient", DummyClient)
    monkeypatch.setattr(main_module, "push_followup_to_travel_server", fake_push_followup_to_travel_server)
    monkeypatch.setattr(main_module, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "new_trace", lambda prefix: f"{prefix}-trace")

    result = await main_module.submit_review(
        {
            "com_name": "示例客户",
            "follow_type": "线下跟进",
            "review_date": "2026-06-08",
            "review_record": "本次完成现场跟进",
            "if_tuisong": "是",
        },
        user={"integrate_id": "tester", "username": "tester"},
        db=db,
    )

    assert result["message"] == "跟进记录已成功提交到简道云"
    assert result["travel_push"]["ok"] is True
    assert pushed["url"] == "http://121.199.167.115:2220/dataway/service/success_chuchai"
    assert pushed["secret"] == ""
    assert pushed["payload"]["op"] == "data_create"
    assert pushed["payload"]["data"]["_id"] == "row-1"

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
from app.services.followup_yuqi import apply_followup_yuqi_fields, extract_followup_yuqi_id  # noqa: E402


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


def test_followup_yuqi_fields_use_new_subform_shape():
    payload = {}

    apply_followup_yuqi_fields(
        payload,
        field_mappings={"jiandaoyun": {"forms": {"跟进记录": {}}}},
        yuqi_id="yuqi-row-1",
        yuqi_record={
            "detail_brief": "BI推广（数字人才）",
            "detail": "各业务部门能够使用BI自助分析",
            "yuqi_status": "进行中",
            "yuqi_id": "uuid-1",
            "cont_name_array": "张三",
        },
    )

    rows = payload["_widget_1780904531626"]["value"]
    assert rows[0]["_widget_1780974773924"]["value"] == {"id": "yuqi-row-1"}
    assert rows[0]["_widget_1780974773919"]["value"] == "张三"
    assert rows[0]["_widget_1780974773920"]["value"] == "BI推广（数字人才）"
    assert rows[0]["_widget_1780974773921"]["value"] == "各业务部门能够使用BI自助分析"
    assert rows[0]["_widget_1780974773922"]["value"] == "进行中"
    assert rows[0]["_widget_1780997127334"]["value"] == "uuid-1"
    assert "review_yuqi_id" not in payload
    assert "_widget_1757576851901" not in payload


def test_extract_followup_yuqi_id_prefers_new_subform_linkdata_id():
    row = {
        "_widget_1780904531626": [{
            "_widget_1780974773924": {"id": "yuqi-row-1"},
            "_widget_1780997127334": "business-uuid-1",
        }],
        "yuqi_id_concat": "business-uuid-1",
        "review_yuqi_id": "legacy-id",
    }

    assert extract_followup_yuqi_id(row) == "yuqi-row-1"


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


@pytest.mark.asyncio
async def test_submit_review_writes_yuqi_subform_from_selected_expectation(monkeypatch):
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
        field_mappings={
            "jiandaoyun": {
                "forms": {
                    "预期表": {"entry_id": "yuqi-entry"},
                    "跟进记录": {"entry_id": "followup-entry"},
                },
                "followup_push": {"enabled": False},
            }
        },
    )
    db = DummyDB(cfg)
    captured = {}

    class DummyWriter:
        def __init__(self, *args, **kwargs):
            pass

        async def create_record(self, entry_id, data):
            captured["entry_id"] = entry_id
            captured["data"] = data
            return {"success": True, "data": {"_id": "row-1"}}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def query_single_data(self, app_id, entry_id, data_id):
            assert app_id == "app-1"
            assert entry_id == "yuqi-entry"
            assert data_id == "yuqi-row-1"
            return {
                "data": {
                    "_id": "yuqi-row-1",
                    "detail_brief": "AI产品了解与试用",
                    "detail": "希望推进AI产品试用",
                    "yuqi_status": "进行中",
                    "yuqi_id": "uuid-1",
                    "cont_name_array": "李四",
                }
            }

    monkeypatch.setattr(main_module, "decrypt_secret", lambda value: "api-key")
    monkeypatch.setattr(main_module, "JiandaoyunWriter", DummyWriter)
    monkeypatch.setattr(main_module, "JiandaoyunClient", DummyClient)
    monkeypatch.setattr(main_module, "emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "new_trace", lambda prefix: f"{prefix}-trace")

    result = await main_module.submit_review(
        {
            "com_name": "示例客户",
            "follow_type": "线下跟进",
            "review_date": "2026-06-10",
            "review_record": "本次完成现场跟进",
            "yuqi_id": "yuqi-row-1",
        },
        user={"integrate_id": "tester", "username": "tester"},
        db=db,
    )

    assert result["message"] == "跟进记录已成功提交到简道云"
    assert captured["entry_id"] == "followup-entry"
    rows = captured["data"]["_widget_1780904531626"]["value"]
    assert rows[0]["_widget_1780974773924"]["value"] == {"id": "yuqi-row-1"}
    assert rows[0]["_widget_1780974773920"]["value"] == "AI产品了解与试用"
    assert rows[0]["_widget_1780974773921"]["value"] == "希望推进AI产品试用"
    assert rows[0]["_widget_1780974773922"]["value"] == "进行中"
    assert rows[0]["_widget_1780997127334"]["value"] == "uuid-1"
    assert "review_yuqi_id" not in captured["data"]
    assert "_widget_1757576851901" not in captured["data"]

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import power_map_service  # noqa: E402


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, *, params, headers=None, cookies=None):
        self.calls.append(dict(params))
        if params == {"prj_type": "company", "prj_id": "customer-1"}:
            return _FakeResponse(
                {
                    "company_name": "盐城市联鑫钢铁有限公司",
                    "version_info": [
                        {
                            "value": "real-version",
                            "text": "【主】公司数据",
                        }
                    ],
                    "node_info": [],
                    "edge_info": [],
                }
            )
        if params == {"prj_type": "opp", "ver_info": "real-version", "prj_id": "customer-1"}:
            return _FakeResponse({"node_info": [], "edge_info": []})
        if params.get("com_id") == "customer-1" or params.get("ver_info") == "foreign-version":
            return _FakeResponse(
                {
                    "company_name": "",
                    "version_info": [{"value": "foreign-version", "text": "【主】公司数据"}],
                    "node_info": [{"id": "bad-node", "name": "科技信息部"}],
                    "edge_info": [],
                }
            )
        raise AssertionError(f"unexpected BI params: {params}")


def _cfg():
    return SimpleNamespace(
        power_map_base_url="https://bi.example.test",
        power_map_get_path="/getInfo",
        power_map_update_path="/upInfo",
        power_map_auth_token_encrypted="",
    )


def test_fetch_from_external_does_not_fallback_to_global_com_id_graph(monkeypatch):
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(power_map_service.httpx, "AsyncClient", _FakeAsyncClient)

    data = asyncio.run(
        power_map_service._fetch_from_external(
            _cfg(),
            "customer-1",
            current_user=None,
            version="foreign-version",
        )
    )

    assert data["company_name"] == "盐城市联鑫钢铁有限公司"
    assert data["version_info"][0]["value"] == "real-version"
    assert data["nodes"] == []
    assert {"com_id": "customer-1"} not in _FakeAsyncClient.calls
    assert {
        "prj_type": "opp",
        "ver_info": "foreign-version",
        "prj_id": "customer-1",
    } not in _FakeAsyncClient.calls

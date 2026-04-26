from __future__ import annotations

from typing import Any

import httpx


# Widget type mapping reference:
# text -> String
# textarea -> String
# number -> Number
# datetime -> String (ISO 8601)
# radiogroup -> String
# checkboxgroup -> Array[String]
# combo -> String
# combocheck -> Array[String]
# subform -> Array[Object] (with nested items)
# linkdata -> JSON {id: "..."}
# lookup -> String (data id)
# phone -> JSON {phone, verified}
# user -> JSON {name, username, ...}
# address -> JSON {province, city, ...}
# richtext -> JSON {html, attachments}


class JiandaoyunClientError(Exception):
    """Base exception for Jiandaoyun client failures."""


class JiandaoyunClient:
    def __init__(self, api_key: str):
        self.api_key = api_key.strip()
        self.v5_base_url = "https://api.jiandaoyun.com/api/v5"
        self.v2_base_url = "https://api.jiandaoyun.com/api/v2"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _raise_for_status(status_code: int, body: str) -> None:
        code = None
        try:
            import json

            parsed = json.loads(body or "{}")
            code = parsed.get("code")
        except Exception:
            code = None
        if code in {8303, 8304}:
            raise JiandaoyunClientError("请求频率超限，请稍后重试")
        if status_code == 401:
            raise JiandaoyunClientError("API Key 无效或已过期")
        if status_code == 404:
            raise JiandaoyunClientError("app_id 或 entry_id 不存在")
        if status_code == 429:
            raise JiandaoyunClientError("请求频率超限，请稍后重试")
        raise JiandaoyunClientError(f"简道云接口调用失败: status={status_code}, body={body}")

    async def fetch_form_widgets(self, app_id: str, entry_id: str) -> dict[str, Any]:
        """
        拉取指定表单的完整字段结构。
        返回原始 JSON（包含 widgets 数组）。
        如果 V5 失败，自动降级到 V2。
        """
        payload = {"app_id": app_id, "entry_id": entry_id}
        timeout = httpx.Timeout(30.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            v5_url = f"{self.v5_base_url}/app/entry/widget/list"
            v5_response = await client.post(v5_url, headers=self._headers, json=payload)
            if v5_response.status_code < 400:
                return v5_response.json()

            # Fallback to V2 when V5 request fails.
            v2_url = f"{self.v2_base_url}/app/{app_id}/entry/{entry_id}/widgets"
            v2_response = await client.post(v2_url, headers=self._headers, json={})
            if v2_response.status_code < 400:
                return v2_response.json()

            # Surface the original V5 status mapping when both fail.
            self._raise_for_status(v5_response.status_code, v5_response.text)

    async def query_data_list(
        self,
        app_id: str,
        entry_id: str,
        limit: int = 10,
        fields: list[str] | None = None,
        filter_condition: dict[str, Any] | None = None,
        data_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "app_id": app_id,
            "entry_id": entry_id,
            "limit": limit,
        }
        if fields:
            payload["fields"] = fields
        if filter_condition:
            payload["filter"] = filter_condition
        if data_id:
            payload["data_id"] = data_id

        url = f"{self.v5_base_url}/app/entry/data/list"
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            v5_response = await client.post(url, headers=self._headers, json=payload)
            if v5_response.status_code < 400:
                return v5_response.json()
            v2_url = f"{self.v2_base_url}/app/{app_id}/entry/{entry_id}/data/list"
            v2_response = await client.post(v2_url, headers=self._headers, json=payload)
            if v2_response.status_code < 400:
                return v2_response.json()
        self._raise_for_status(v5_response.status_code, v5_response.text)

    async def query_single_data(self, app_id: str, entry_id: str, data_id: str) -> dict[str, Any]:
        payload = {"app_id": app_id, "entry_id": entry_id, "data_id": data_id}
        url = f"{self.v5_base_url}/app/entry/data/get"
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            v5_response = await client.post(url, headers=self._headers, json=payload)
            if v5_response.status_code < 400:
                return v5_response.json()
            v2_url = f"{self.v2_base_url}/app/{app_id}/entry/{entry_id}/data/get"
            v2_response = await client.post(v2_url, headers=self._headers, json=payload)
            if v2_response.status_code < 400:
                return v2_response.json()
        self._raise_for_status(v5_response.status_code, v5_response.text)

    async def create_data(self, app_id: str, entry_id: str, data: dict[str, Any]) -> dict[str, Any]:
        payload = {"app_id": app_id, "entry_id": entry_id, "data": data}
        url = f"{self.v5_base_url}/app/entry/data/create"
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(url, headers=self._headers, json=payload)
        if response.status_code >= 400:
            self._raise_for_status(response.status_code, response.text)
        return response.json()

    async def update_data(self, app_id: str, entry_id: str, data_id: str, data: dict[str, Any]) -> dict[str, Any]:
        payload = {"app_id": app_id, "entry_id": entry_id, "data_id": data_id, "data": data}
        url = f"{self.v5_base_url}/app/entry/data/update"
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(url, headers=self._headers, json=payload)
        if response.status_code >= 400:
            self._raise_for_status(response.status_code, response.text)
        return response.json()

    async def delete_data(self, app_id: str, entry_id: str, data_id: str) -> dict[str, Any]:
        payload = {"app_id": app_id, "entry_id": entry_id, "data_id": data_id}
        url = f"{self.v5_base_url}/app/entry/data/delete"
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(url, headers=self._headers, json=payload)
        if response.status_code >= 400:
            self._raise_for_status(response.status_code, response.text)
        return response.json()

    async def fetch_form_data_list(
        self,
        app_id: str,
        entry_id: str,
        limit: int = 10,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self.query_data_list(app_id=app_id, entry_id=entry_id, limit=limit, fields=fields)

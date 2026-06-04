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
        timeout = httpx.Timeout(3600.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            # 首先尝试 V5 API
            v5_url = f"{self.v5_base_url}/app/entry/widget/list"
            try:
                v5_response = await client.post(v5_url, headers=self._headers, json=payload)
                if v5_response.status_code < 400:
                    return v5_response.json()
                # 处理特定的错误代码
                if v5_response.status_code == 400:
                    try:
                        error_data = v5_response.json()
                        if error_data.get("code") == 3005:
                            # 参数错误，可能 entry_id 不存在
                            raise JiandaoyunClientError(f"表单ID无效: {entry_id}")
                    except Exception:
                        pass
            except Exception as e:
                if isinstance(e, JiandaoyunClientError):
                    raise

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
            "limit": max(1, min(limit, 100)),  # 确保 limit 在 1-100 之间
        }
        if fields:
            payload["fields"] = fields
        if filter_condition:
            payload["filter"] = filter_condition
        if data_id:
            payload["data_id"] = data_id

        url = f"{self.v5_base_url}/app/entry/data/list"
        async with httpx.AsyncClient(timeout=httpx.Timeout(3600.0)) as client:
            try:
                v5_response = await client.post(url, headers=self._headers, json=payload)
                if v5_response.status_code < 400:
                    return v5_response.json()
                # 处理特定的错误代码
                if v5_response.status_code == 400:
                    try:
                        error_data = v5_response.json()
                        if error_data.get("code") == 3005:
                            # 参数错误，可能 entry_id 不存在
                            raise JiandaoyunClientError(f"表单ID无效: {entry_id}")
                    except Exception:
                        pass
            except Exception as e:
                if isinstance(e, JiandaoyunClientError):
                    raise

            # Fallback to V2 when V5 request fails.
            v2_url = f"{self.v2_base_url}/app/{app_id}/entry/{entry_id}/data/list"
            v2_response = await client.post(v2_url, headers=self._headers, json=payload)
            if v2_response.status_code < 400:
                return v2_response.json()
        self._raise_for_status(v5_response.status_code if 'v5_response' in locals() else 500, 
                               v5_response.text if 'v5_response' in locals() else "Failed to query data")

    async def query_single_data(self, app_id: str, entry_id: str, data_id: str) -> dict[str, Any]:
        payload = {"app_id": app_id, "entry_id": entry_id, "data_id": data_id}
        url = f"{self.v5_base_url}/app/entry/data/get"
        async with httpx.AsyncClient(timeout=httpx.Timeout(3600.0)) as client:
            v5_response = await client.post(url, headers=self._headers, json=payload)
            if v5_response.status_code < 400:
                return v5_response.json()
            v2_url = f"{self.v2_base_url}/app/{app_id}/entry/{entry_id}/data/get"
            v2_response = await client.post(v2_url, headers=self._headers, json=payload)
            if v2_response.status_code < 400:
                return v2_response.json()
        self._raise_for_status(v5_response.status_code, v5_response.text)

    async def create_data(self, app_id: str, entry_id: str, data: dict[str, Any], data_creator: str = "") -> dict[str, Any]:
        payload = {"app_id": app_id, "entry_id": entry_id, "data": data}
        if data_creator:
            payload["data_creator"] = data_creator
        url = f"{self.v5_base_url}/app/entry/data/create"
        async with httpx.AsyncClient(timeout=httpx.Timeout(3600.0)) as client:
            response = await client.post(url, headers=self._headers, json=payload)
        if response.status_code >= 400:
            self._raise_for_status(response.status_code, response.text)
        return response.json()

    async def update_data(self, app_id: str, entry_id: str, data_id: str, data: dict[str, Any], data_creator: str = "") -> dict[str, Any]:
        payload = {"app_id": app_id, "entry_id": entry_id, "data_id": data_id, "data": data}
        if data_creator:
            payload["data_creator"] = data_creator
        url = f"{self.v5_base_url}/app/entry/data/update"
        async with httpx.AsyncClient(timeout=httpx.Timeout(3600.0)) as client:
            response = await client.post(url, headers=self._headers, json=payload)
        if response.status_code >= 400:
            self._raise_for_status(response.status_code, response.text)
        return response.json()

    async def delete_data(self, app_id: str, entry_id: str, data_id: str) -> dict[str, Any]:
        payload = {"app_id": app_id, "entry_id": entry_id, "data_id": data_id}
        url = f"{self.v5_base_url}/app/entry/data/delete"
        async with httpx.AsyncClient(timeout=httpx.Timeout(3600.0)) as client:
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

    async def fetch_entry_data_list(
        self,
        app_id: str,
        entry_id: str,
        *,
        page_size: int = 100,
        max_pages: int = 50,
        fields: list[str] | None = None,
        filter_condition: dict[str, Any] | None = None,
        page_sleep_seconds: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Fetch ALL records from a Jiandaoyun form by paging through `data_id` cursor.

        Returns a flat list of raw record dicts. Uses the existing v5->v2 fallback
        in `query_data_list`. Sleeps between pages to respect rate limits.
        """
        import asyncio

        all_rows: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(max_pages):
            page = await self.query_data_list(
                app_id=app_id,
                entry_id=entry_id,
                limit=max(1, min(page_size, 100)),
                fields=fields,
                filter_condition=filter_condition,
                data_id=cursor,
            )
            batch = page.get("data", []) or []
            if not batch:
                break
            all_rows.extend(batch)
            next_cursor = batch[-1].get("_id")
            if not next_cursor or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            if len(batch) < page_size:
                break
            await asyncio.sleep(page_sleep_seconds)
        return all_rows

from __future__ import annotations

from typing import Any

from .field_safety import check_operation_cards
from .jiandaoyun_client import JiandaoyunClient, JiandaoyunClientError


def _err(code: str, detail: str) -> dict[str, Any]:
    return {"success": False, "error_code": code, "detail": detail}


class JiandaoyunWriter:
    def __init__(self, api_key: str, app_id: str, data_creator: str = ""):
        self.client = JiandaoyunClient(api_key=api_key)
        self.app_id = app_id
        self.data_creator = data_creator

    async def create_record(self, entry_id: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self.client.create_data(self.app_id, entry_id, data, data_creator=self.data_creator)
            return {"success": True, **result}
        except JiandaoyunClientError as exc:
            return _err("create_failed", str(exc))

    async def update_record(self, entry_id: str, data_id: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self.client.update_data(self.app_id, entry_id, data_id, data, data_creator=self.data_creator)
            return {"success": True, **result}
        except JiandaoyunClientError as exc:
            return _err("update_failed", str(exc))

    async def delete_record(self, entry_id: str, data_id: str) -> dict[str, Any]:
        try:
            result = await self.client.delete_data(self.app_id, entry_id, data_id)
            return {"success": True, "data": result}
        except JiandaoyunClientError as exc:
            return _err("delete_failed", str(exc))

    async def update_subform_append(
        self,
        entry_id: str,
        data_id: str,
        subform_widget: str,
        new_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            current = await self.client.query_single_data(self.app_id, entry_id, data_id)
            data = current.get("data", {}) or {}
            existing_rows = data.get(subform_widget, []) or []
            sanitized_existing: list[dict[str, Any]] = []
            for row in existing_rows:
                if not isinstance(row, dict):
                    continue
                sanitized: dict[str, Any] = {}
                for k, v in row.items():
                    if k == "_id":
                        sanitized["_id"] = {"value": v}
                    else:
                        sanitized[k] = {"value": v}
                sanitized_existing.append(sanitized)
            final_rows = sanitized_existing + new_rows
            payload = {subform_widget: {"value": final_rows}}
            await self.client.update_data(self.app_id, entry_id, data_id, payload)
            verify = await self.client.query_single_data(self.app_id, entry_id, data_id)
            after_rows = (verify.get("data", {}) or {}).get(subform_widget, []) or []
            if len(after_rows) != len(existing_rows) + len(new_rows):
                return _err("subform_verify_failed", "subform row count mismatch after append")
            return {"success": True, "data": verify}
        except JiandaoyunClientError as exc:
            return _err("subform_append_failed", str(exc))

    def check_cards_safety(self, cards: list[dict[str, Any]], form_config: dict[str, Any]) -> list[dict[str, Any]]:
        return check_operation_cards(cards, form_config)

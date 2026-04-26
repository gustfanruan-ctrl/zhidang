from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .jiandaoyun_client import JiandaoyunClient


class MatchResult(BaseModel):
    status: str
    candidates: list[dict[str, Any]]


async def match_customer(client: JiandaoyunClient, app_id: str, entry_id: str, name: str, limit: int = 10) -> MatchResult:
    keyword = (name or "").strip()
    if not keyword:
        return MatchResult(status="not_found", candidates=[])
    response = await client.query_data_list(
        app_id=app_id,
        entry_id=entry_id,
        fields=["comname_01", "com_name", "com_type", "revenue_level", "if_access", "follow_form"],
        filter_condition={
            "rel": "or",
            "cond": [
                {
                    "field": "comname_01",
                    "type": "text",
                    "method": "like",
                    "value": [keyword],
                },
                {
                    "field": "com_name",
                    "type": "text",
                    "method": "like",
                    "value": [keyword],
                },
            ],
        },
        limit=limit,
    )
    candidates = response.get("data", [])
    if len(candidates) == 1:
        status = "matched"
    elif len(candidates) > 1:
        status = "multiple"
    else:
        status = "not_found"
    return MatchResult(status=status, candidates=candidates)


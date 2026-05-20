"""
简道云跟进记录 → FollowupRecord scraping service.

Fetches all records from the 简道云 followup form, deduplicates by
source_id (= 简道云 _id), and inserts new ones into the followup_records table.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FollowupRecord
from .jiandaoyun_client import JiandaoyunClient, JiandaoyunClientError

logger = logging.getLogger("zhidang.followup_scraper")

FOLLOWUP_APP_ID = "5dcbcb63d6e30c000692464e"
FOLLOWUP_ENTRY_ID = "670a28334883adafb152a869"

# Text-bearing fields to concatenate into raw_text (in display order).
_TEXT_FIELDS = ("review_record", "background", "conclusion", "_widget_1728719176248")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("value", "name", "label", "text"):
            if key in value and value[key]:
                return str(value[key])
        return ""
    if isinstance(value, list):
        return ", ".join(_stringify(v) for v in value if v)
    return str(value)


def _extract_user_name(value: Any) -> str:
    """JDY user-type fields are {"name": "Gust-张小洋", "username": "Gust.Zhang"} or a list of those."""
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, dict):
        return value.get("name") or value.get("username") or ""
    if isinstance(value, str):
        return value
    return ""


def _hash_company_id(company_name: str) -> str:
    return hashlib.sha256((company_name or "").encode("utf-8")).hexdigest()


def build_raw_text(row: dict[str, Any]) -> str:
    """Concatenate all text-bearing fields into a single raw_text string."""
    parts: list[str] = []
    for field in _TEXT_FIELDS:
        text = _stringify(row.get(field)).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def row_to_followup_kwargs(row: dict[str, Any]) -> dict[str, Any] | None:
    """Map a 简道云 row into FollowupRecord kwargs. Returns None if no _id."""
    source_id = row.get("_id")
    if not source_id:
        return None
    company_name = _stringify(row.get("com_name")).strip()
    comid = _stringify(row.get("comid")).strip()
    follower_name = _extract_user_name(row.get("follower"))
    raw_text = build_raw_text(row) or _stringify(row.get("review_record"))
    review_date = _stringify(row.get("review_date")).strip() or None
    follow_type = _stringify(row.get("follow_type")).strip() or None
    title_bits = [bit for bit in (company_name, review_date, follow_type) if bit]
    title = " · ".join(title_bits) if title_bits else (source_id[:24])
    return {
        "source": "jiandaoyun",
        "source_id": str(source_id),
        "title": title[:255],
        "raw_text": raw_text or "(无文本内容)",
        "segments": None,
        "input_type": "followup",
        "status": "parsed",
        "company_id": comid or (_hash_company_id(company_name) if company_name else None),
        "company_name": company_name or None,
        "sso_user_name": follower_name or None,
        "sso_user_id": None,
        "review_date": review_date,
        "follow_type": follow_type,
        "raw_record": row,
    }


async def fetch_and_store(
    db: Session,
    api_key: str,
    *,
    page_size: int = 100,
    max_pages: int = 50,
) -> dict[str, int]:
    """Fetch all records from JDY and upsert new ones. Returns counters."""
    client = JiandaoyunClient(api_key=api_key)
    try:
        rows = await client.fetch_entry_data_list(
            app_id=FOLLOWUP_APP_ID,
            entry_id=FOLLOWUP_ENTRY_ID,
            page_size=page_size,
            max_pages=max_pages,
        )
    except JiandaoyunClientError:
        logger.exception("Failed to fetch followup records from JDY")
        raise

    existing_ids = {
        sid for (sid,) in db.execute(
            select(FollowupRecord.source_id).where(FollowupRecord.source_id.is_not(None))
        ).all()
    }
    fetched = len(rows)
    inserted = 0
    skipped = 0
    for row in rows:
        kwargs = row_to_followup_kwargs(row)
        if not kwargs:
            skipped += 1
            continue
        if kwargs["source_id"] in existing_ids:
            skipped += 1
            continue
        record = FollowupRecord(**kwargs)
        db.add(record)
        existing_ids.add(kwargs["source_id"])
        inserted += 1
    db.commit()
    logger.info(
        "Followup scrape: fetched=%d inserted=%d skipped=%d at=%s",
        fetched, inserted, skipped, datetime.utcnow().isoformat(),
    )
    return {"fetched": fetched, "inserted": inserted, "skipped": skipped}

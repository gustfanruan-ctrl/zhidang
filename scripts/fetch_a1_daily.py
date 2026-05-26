#!/usr/bin/env python3
"""Fetch A1 transcripts from CRM BI into the transcript DB.

Cron runs this several times a day with a short rolling window so records that
arrive late, or around midnight, are still picked up. Deduplication is by
``Transcript.source_id``.
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from uuid import uuid4

sys.path.insert(0, "/app")

from backend.app.database import SessionLocal
from backend.app.models import Transcript

BASE_URL = "https://crm.finereporthelp.com/WebReport/decision/url/pub/crm/data"
BI_ID = "5074008d30ba433aa54c8ddaee919cec"
BI_SECRET = "123"
CN_TZ = timezone(timedelta(hours=8))


def date_range(days: int, explicit_date: str | None = None) -> list[str]:
    if explicit_date:
        return [explicit_date]
    today = datetime.now(CN_TZ).date()
    window = max(1, days)
    return [(today - timedelta(days=offset)).isoformat() for offset in range(window)]


def fetch_transcripts(date_str: str) -> list[dict]:
    params = urllib.parse.urlencode({"id": BI_ID, "secret": BI_SECRET, "date": date_str})
    url = f"{BASE_URL}?{params}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("success") is False:
        raise RuntimeError(f"BI returned failure: {data.get('error') or data}")
    return data.get("data", []) or []


def insert_records(db, rows: list[dict]) -> tuple[int, int, int]:
    new = 0
    skipped = 0
    empty = 0
    for item in rows:
        task_uuid = str(item.get("task_uuid") or item.get("source_id") or "").strip()
        if not task_uuid:
            skipped += 1
            continue
        if db.query(Transcript).filter(Transcript.source_id == task_uuid).first():
            skipped += 1
            continue
        raw_text = (item.get("transcript_text") or item.get("summary_text") or "").strip()
        if not raw_text:
            empty += 1
            continue

        db.add(Transcript(
            id=str(uuid4()),
            source="dingtalk",
            source_id=task_uuid,
            title=item.get("title", "") or "Untitled",
            raw_text=raw_text,
            input_type="text",
            status="parsed",
            sso_user_name=item.get("user_name", ""),
            sso_user_id=item.get("user_username", ""),
            created_at=datetime.now(timezone.utc),
        ))
        new += 1
    return new, skipped, empty


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch A1 transcripts into Zhidang")
    parser.add_argument("--date", help="Fetch one date only, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=2, help="Rolling day window including today")
    args = parser.parse_args()

    db = SessionLocal()
    total_new = 0
    total_skipped = 0
    total_empty = 0
    try:
        for date_str in date_range(args.days, args.date):
            rows = fetch_transcripts(date_str)
            new, skipped, empty = insert_records(db, rows)
            db.commit()
            total_new += new
            total_skipped += skipped
            total_empty += empty
            print(f"[{date_str}] A1 fetch: fetched={len(rows)} new={new} skipped={skipped} empty={empty}")
    except Exception as exc:
        db.rollback()
        print(f"[ERROR] A1 fetch failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"[DONE] A1 fetch summary: new={total_new} skipped={total_skipped} empty={total_empty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

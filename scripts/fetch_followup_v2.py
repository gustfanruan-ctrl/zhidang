"""
Fetch 简道云 followup records with date filtering, field mapping, and JSON export.

Usage:
    # Manual run: last 90 days
    python3 fetch_followup_v2.py

    # Specific date range
    python3 fetch_followup_v2.py --start 2026-02-01 --end 2026-05-20

    # Export only (skip DB insert)
    python3 fetch_followup_v2.py --export-only --days 30

    # Daily cron mode: today's records only
    python3 fetch_followup_v2.py --today

Saves output JSON to /data/followup_records.json (inside container) or
/opt/zhidang/data/followup_records_YYYYMMDD.json on the host.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, "/app")

import httpx
from backend.app.database import SessionLocal
from backend.app.models import FollowupRecord

APP_ID = "5dcbcb63d6e30c000692464e"
ENTRY_ID = "670a28334883adafb152a869"

# API key — auto-loaded from SystemConfig if available, else hardcoded fallback
_API_KEY = None
_API_KEY_FILE = "/opt/data/.jdkey"


def get_api_key() -> str:
    global _API_KEY
    if _API_KEY:
        return _API_KEY

    # Try from file first (secure local stash)
    if os.path.exists(_API_KEY_FILE):
        _API_KEY = open(_API_KEY_FILE).read().strip()
        return _API_KEY

    # Try from DB SystemConfig
    try:
        from backend.app.main import ensure_system_config  # noqa: E402
        from backend.app.services.crypto_utils import decrypt_secret  # noqa: E402

        db = SessionLocal()
        cfg = ensure_system_config(db)
        if cfg.jiandaoyun_api_key_encrypted:
            _API_KEY = decrypt_secret(cfg.jiandaoyun_api_key_encrypted)
            db.close()
            return _API_KEY
        db.close()
    except Exception:
        pass

    # Fallback — user should set env or file
    _API_KEY = os.environ.get("JDY_API_KEY", "")
    return _API_KEY


def build_date_filter(start_date: str, end_date: str | None = None) -> dict:
    """Build 简道云 v5 filter_condition for review_date range."""
    conds = [
        {
            "field": "review_date",
            "type": "datetime",
            "method": "ge",
            "value": f"{start_date}T00:00:00.000+08:00",
        }
    ]
    if end_date:
        conds.append(
            {
                "field": "review_date",
                "type": "datetime",
                "method": "le",
                "value": f"{end_date}T23:59:59.999+08:00",
            }
        )
    return {"rel": "and", "cond": conds}


def parse_review_date(row: dict) -> str:
    """Extract review_date as ISO date string, handling 简道云 datetime format."""
    val = row.get("review_date")
    if isinstance(val, str) and val:
        return val[:10]  # "2026-05-19T12:00:00.000Z" → "2026-05-19"
    if isinstance(val, dict):
        return str(val.get("name") or val.get("value") or "")[:10]
    return ""


def client_filter(rows: list[dict], start_date: str, end_date: str | None = None) -> list[dict]:
    """Client-side date filter — safety net in case 简道云 API ignores filter_cond."""
    filtered = []
    for row in rows:
        rd = parse_review_date(row)
        if not rd:
            continue  # Skip records without review_date
        if rd < start_date[:10]:
            continue
        if end_date and rd > end_date[:10]:
            continue
        filtered.append(row)
    return filtered


async def fetch_with_filter(
    api_key: str,
    start_date: str,
    end_date: str | None = None,
    *,
    page_size: int = 100,
    max_pages: int = 200,
) -> list[dict]:
    """Fetch records from 简道云 v5 API with date filter and data_id cursor."""
    filter_cond = build_date_filter(start_date, end_date)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    all_rows: list[dict] = []
    data_id: str | None = None
    seen_ids: set[str] = set()

    async with httpx.AsyncClient(timeout=30) as client:
        for page in range(max_pages):
            payload: dict = {
                "app_id": APP_ID,
                "entry_id": ENTRY_ID,
                "limit": min(page_size, 100),
                "filter": filter_cond,
            }
            if data_id:
                payload["data_id"] = data_id

            resp = await client.post(
                "https://api.jiandaoyun.com/api/v5/app/entry/data/list",
                headers=headers,
                json=payload,
            )

            if resp.status_code != 200:
                print(f"[ERROR] API HTTP {resp.status_code}: {resp.text[:300]}")
                break

            body = resp.json()
            batch = body.get("data", [])
            if not batch:
                break

            all_rows.extend(batch)
            last_id = batch[-1].get("_id", "")
            if not last_id or last_id in seen_ids:
                break
            seen_ids.add(last_id)
            data_id = last_id

            print(f"  Page {page + 1}: {len(batch)} records (total: {len(all_rows)})")

            if len(batch) < page_size:
                break
            await asyncio.sleep(0.3)

    # Client-side filter as safety net (JDY v5 datetime filter is unreliable)
    if all_rows:
        before = len(all_rows)
        all_rows = client_filter(all_rows, start_date, end_date)
        if before != len(all_rows):
            print(f"  [FILTER] Client-side: {before} → {len(all_rows)} (date range)")

    return all_rows


def extract_field(row: dict, field: str, default: str = "") -> str:
    """Extract a string value from a 简道云 record field (handles dict, list, str)."""
    val = row.get(field)
    if val is None:
        return default
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return val.get("name") or val.get("value") or val.get("label") or str(val)
    if isinstance(val, list) and val:
        first = val[0]
        if isinstance(first, dict):
            return first.get("name") or str(first)
        return str(first)
    return str(val)


def is_distinct_record(row: dict, seen_source_ids: set[str]) -> bool:
    """Check if this record is not yet in the DB."""
    sid = row.get("_id", "")
    return bool(sid and sid not in seen_source_ids)


async def save_to_json(records: list[dict], filepath: str):
    """Save raw records to a JSON file."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, default=str)
    size_kb = os.path.getsize(filepath) / 1024
    print(f"[EXPORT] {len(records)} records → {filepath} ({size_kb:.1f} KB)")


async def insert_to_db(records: list[dict]) -> dict[str, int]:
    """Insert new records into followup_records table, dedup by source_id."""
    db = SessionLocal()
    existing = {sid for (sid,) in db.query(FollowupRecord.source_id).filter(
        FollowupRecord.source_id.is_not(None)
    ).all()}

    inserted = 0
    skipped = 0

    for row in records:
        source_id = row.get("_id", "")
        if not source_id or source_id in existing:
            skipped += 1
            continue

        # Extract with proper field mapping
        com_name = extract_field(row, "com_name")
        com_id = extract_field(row, "_widget_1744600409845") or None
        follower_name = extract_field(row, "follower")
        follow_type = extract_field(row, "follow_type")
        review_date = extract_field(row, "review_date")
        review_record = extract_field(row, "review_record")

        title = f"{com_name} - {follower_name} - {follow_type}" if com_name else f"{follower_name} - {follow_type}"
        raw_text = review_record or json.dumps(row, ensure_ascii=False)

        rec = FollowupRecord(
            id=str(uuid4()),
            source="jiandaoyun",
            source_id=source_id,
            title=title[:255],
            raw_text=raw_text,
            company_id=com_id,
            company_name=com_name,
            sso_user_name=follower_name,
            review_date=review_date or None,
            follow_type=follow_type or None,
            raw_record=row,
            status="parsed",
            created_at=datetime.now(timezone.utc),
        )
        db.add(rec)
        existing.add(source_id)
        inserted += 1
        print(f"  + {title[:80]} | {review_date[:10] if review_date else 'N/A'}")

        # Commit every 100 to avoid huge transactions
        if inserted % 100 == 0:
            db.commit()
            print(f"  ... committed {inserted} so far")

    db.commit()
    db.close()
    return {"inserted": inserted, "skipped": skipped}


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch 简道云 followup records")
    parser.add_argument("--days", type=int, default=90, help="Number of days back (default: 90)")
    parser.add_argument("--start", help="Start date YYYY-MM-DD (overrides --days)")
    parser.add_argument("--end", help="End date YYYY-MM-DD")
    parser.add_argument("--today", action="store_true", help="Fetch today's records only")
    parser.add_argument("--export-only", action="store_true", help="Export JSON only, skip DB insert")
    parser.add_argument("--output", help="Output JSON file path")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print("[FATAL] No API key found. Set JDY_API_KEY env or configure in SystemConfig.")
        sys.exit(1)

    # Determine date range
    if args.today:
        today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        start_date = today
        end_date = today
    elif args.start:
        start_date = args.start
        end_date = args.end or args.start
    else:
        end = datetime.now(timezone.utc).astimezone()
        start = end - timedelta(days=args.days)
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")

    # Output path
    if args.output:
        outpath = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        outpath = f"/data/followup_records_{timestamp}.json"

    print(f"[FETCH] Date range: {start_date} → {end_date or 'now'}")
    records = await fetch_with_filter(api_key, start_date, end_date)
    print(f"\n[DONE] Fetched {len(records)} records")

    if not records:
        print("No records found for this date range.")
        return

    # Save JSON
    await save_to_json(records, outpath)

    # Insert to DB (unless export-only)
    if not args.export_only:
        print("\n[INSERT] Adding to database...")
        result = await insert_to_db(records)
        print(f"[INSERT] New: {result['inserted']}, Skipped: {result['skipped']}")
    else:
        print("[SKIP] DB insert skipped (--export-only)")

    print("\n[COMPLETE] ✓")


if __name__ == "__main__":
    asyncio.run(main())

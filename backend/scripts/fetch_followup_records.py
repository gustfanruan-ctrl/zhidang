"""CLI entry point for scraping 简道云 followup records into the local DB.

Usage:
    python -m backend.scripts.fetch_followup_records --api-key <KEY>
    JIANDAOYUN_API_KEY=<KEY> python -m backend.scripts.fetch_followup_records

The script reads the API key from --api-key, JIANDAOYUN_API_KEY env var,
or (as a fallback) from the encrypted SystemConfig column.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

from backend.app.crypto_utils import decrypt_secret
from backend.app.database import SessionLocal
from backend.app.models import SystemConfig
from backend.app.services.followup_scraper import fetch_and_store


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch 简道云 followup records into local DB.")
    parser.add_argument("--api-key", default=os.getenv("JIANDAOYUN_API_KEY", ""))
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=50)
    return parser.parse_args()


def _resolve_api_key(cli_key: str) -> str:
    if cli_key.strip():
        return cli_key.strip()
    db = SessionLocal()
    try:
        cfg = db.get(SystemConfig, 1)
        if cfg and cfg.jiandaoyun_api_key_encrypted:
            decrypted = decrypt_secret(cfg.jiandaoyun_api_key_encrypted)
            if decrypted:
                return decrypted.strip()
    finally:
        db.close()
    return ""


async def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = _parse_args()
    api_key = _resolve_api_key(args.api_key)
    if not api_key:
        print("ERROR: 简道云 API key not provided (--api-key / JIANDAOYUN_API_KEY / SystemConfig).")
        return 2

    db = SessionLocal()
    try:
        result: dict[str, Any] = await fetch_and_store(
            db,
            api_key=api_key,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )
    finally:
        db.close()

    print(
        f"完成：fetched={result['fetched']} inserted={result['inserted']} skipped={result['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

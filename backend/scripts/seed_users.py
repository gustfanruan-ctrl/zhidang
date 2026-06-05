"""Seed CSM users from csm_users.json into the User table.

Usage:
    python -m backend.scripts.seed_users [path/to/csm_users.json]

Defaults to repo-root csm_users.json. Skips usernames that already exist.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bcrypt
from sqlalchemy import select

from backend.app.database import Base, SessionLocal, engine
from backend.app.models import User

DEFAULT_PASSWORD = "zhidang2026"


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def seed(json_path: Path) -> int:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    raw_users = payload.get("users") if isinstance(payload, dict) else payload
    if not isinstance(raw_users, list):
        raise ValueError(f"Unexpected csm_users.json structure in {json_path}")

    Base.metadata.create_all(bind=engine)

    password_hash = _hash_password(DEFAULT_PASSWORD)
    inserted = 0
    skipped = 0

    with SessionLocal() as db:
        existing = {row[0] for row in db.execute(select(User.username)).all()}
        for entry in raw_users:
            username = (entry.get("username") or "").strip()
            if not username:
                continue
            if username in existing:
                skipped += 1
                continue
            db.add(
                User(
                    username=username,
                    password_hash=password_hash,
                    display_name=entry.get("name"),
                    integrate_id=entry.get("integrate_id"),
                    departments=entry.get("departments") or [],
                    is_active=bool(entry.get("status", 1)),
                )
            )
            existing.add(username)
            inserted += 1
        db.commit()

    print(f"inserted={inserted} skipped={skipped} total={inserted + skipped}")
    return inserted


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        path = Path(argv[1])
    else:
        path = Path(__file__).resolve().parents[2] / "csm_users.json"
    if not path.exists():
        print(f"csm_users.json not found at {path}", file=sys.stderr)
        return 1
    seed(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

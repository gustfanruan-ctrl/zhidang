from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models import SystemConfig


LLM_FIELDS = [
    "llm_provider",
    "llm_base_url",
    "llm_api_key_encrypted",
    "agent_a_model",
    "agent_b_model",
    "nl_chat_model",
    "power_map_llm_model",
    "temperature",
    "max_tokens",
]


def _read_config() -> dict[str, Any]:
    db = SessionLocal()
    try:
        cfg = db.get(SystemConfig, 1)
        if not cfg:
            raise RuntimeError("system_config id=1 not found")
        return {field: getattr(cfg, field) for field in LLM_FIELDS}
    finally:
        db.close()


def _snapshot(path: Path) -> None:
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fields": _read_config(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"snapshot_written={path}")


def _restore(path: Path, *, dry_run: bool) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    fields = payload.get("fields") or {}
    unknown = sorted(set(fields) - set(LLM_FIELDS))
    if unknown:
        raise RuntimeError(f"unknown fields in snapshot: {unknown}")
    db = SessionLocal()
    try:
        cfg = db.get(SystemConfig, 1)
        if not cfg:
            raise RuntimeError("system_config id=1 not found")
        changes = {}
        for field in LLM_FIELDS:
            if field not in fields:
                continue
            old = getattr(cfg, field)
            new = fields[field]
            if old != new:
                changes[field] = {"old": old, "new": new}
                if not dry_run:
                    setattr(cfg, field, new)
        if not dry_run:
            db.commit()
        print(json.dumps({"dry_run": dry_run, "changes": changes}, ensure_ascii=False, indent=2))
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Snapshot or restore Power Map LLM config.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--out", required=True, type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("--infile", required=True, type=Path)
    restore.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.cmd == "snapshot":
        _snapshot(args.out)
    elif args.cmd == "restore":
        _restore(args.infile, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


API_BASE = "https://api.jiandaoyun.com/api/v5"
DEFAULT_APP_ID = "5dcbcb63d6e30c000692464e"
DEFAULT_URLS = [
    "https://www.jiandaoyun.com/dashboard/app/5dcbcb63d6e30c000692464e/form/67f32f3b3b2d63ec45bd252a/data/6864e4b73a26ce3f1c2957ea/qr_link",
    "https://www.jiandaoyun.com/dashboard/app/5dcbcb63d6e30c000692464e/form/67f32f3b3b2d63ec45bd252a/data/69ba1e15b84666562f03294e/qr_link",
    "https://www.jiandaoyun.com/dashboard/app/5dcbcb63d6e30c000692464e/form/678db5c7bd2b1f7e00c1a3cc/data/69eaf8d985e1235865917bf6/qr_link",
    "https://www.jiandaoyun.com/dashboard/app/5dcbcb63d6e30c000692464e/form/678db5c7bd2b1f7e00c1a3cc/data/6964fb47f75fce1f0f8a86b4/qr_link",
]
URL_PATTERN = re.compile(
    r"/app/(?P<app_id>[^/]+)/form/(?P<form_id>[^/]+)/data/(?P<data_id>[^/]+)/qr_link/?$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch specific Jiandaoyun form records from QR links.")
    parser.add_argument("--api-key", default=os.getenv("JIANDAOYUN_API_KEY", "").strip())
    parser.add_argument("--app-id", default=os.getenv("JIANDAOYUN_APP_ID", DEFAULT_APP_ID).strip())
    parser.add_argument("--output", default="")
    parser.add_argument("--url", action="append", default=[])
    return parser.parse_args()


def parse_qr_link(url: str) -> dict[str, str]:
    match = URL_PATTERN.search(url.strip())
    if not match:
        raise ValueError(f"无法解析链接: {url}")
    return {
        "url": url.strip(),
        "app_id": match.group("app_id"),
        "entry_id": match.group("form_id"),
        "data_id": match.group("data_id"),
    }


async def get_data(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    app_id: str,
    entry_id: str,
    data_id: str,
) -> tuple[int, dict[str, Any], str]:
    payload = {"app_id": app_id, "entry_id": entry_id, "data_id": data_id}
    response = await client.post(f"{API_BASE}/app/entry/data/get", headers=headers, json=payload)
    text = response.text
    try:
        parsed = response.json()
    except Exception:
        parsed = {}
    return response.status_code, parsed, text


async def main() -> None:
    args = parse_args()
    if not args.api_key:
        raise SystemExit("缺少 API key，请配置 JIANDAOYUN_API_KEY 或通过 --api-key 传入。")

    urls = args.url if args.url else list(DEFAULT_URLS)
    parsed_targets = [parse_qr_link(url) for url in urls]
    headers = {"Authorization": f"Bearer {args.api_key}", "Content-Type": "application/json"}

    output_path = (
        Path(args.output).resolve()
        if args.output.strip()
        else (Path(__file__).resolve().parent / "output" / "excellent_yuqi_changjing_data.json")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        for item in parsed_targets:
            target_app_id = item["app_id"] if item["app_id"] else args.app_id
            status_code, response_json, raw = await get_data(
                client=client,
                headers=headers,
                app_id=target_app_id,
                entry_id=item["entry_id"],
                data_id=item["data_id"],
            )
            record = {
                **item,
                "status_code": status_code,
                "ok": status_code == 200 and bool(response_json.get("data")),
                "response": response_json if status_code == 200 else {"raw": raw},
            }
            results.append(record)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "app_id": args.app_id,
        "total": len(results),
        "success": sum(1 for r in results if r["ok"]),
        "records": results,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已输出: {output_path}")
    print(f"成功: {payload['success']}/{payload['total']}")


if __name__ == "__main__":
    asyncio.run(main())

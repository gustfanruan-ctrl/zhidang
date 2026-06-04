from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.jiandaoyun_client import JiandaoyunClient


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch customer main form structure and data samples.")
    parser.add_argument("--api-key", default=os.getenv("JIANDAOYUN_API_KEY", ""))
    parser.add_argument("--app-id", default=os.getenv("JIANDAOYUN_APP_ID", ""))
    parser.add_argument("--entry-id", default=os.getenv("CUSTOMER_MAIN_ENTRY_ID", ""))
    parser.add_argument("--sample-limit", type=int, default=int(os.getenv("CUSTOMER_MAIN_SAMPLE_LIMIT", "5")))
    return parser.parse_args()


def _require(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"缺少参数: {name}")
    return normalized


def _subfields_text(widget: dict[str, Any]) -> str:
    if widget.get("type") != "subform":
        return "-"
    items = widget.get("items", []) or []
    if not items:
        return "(empty)"
    return ", ".join(f"{i.get('label', '-')}" f"({i.get('type', '-')})" for i in items)


def _extract_field_samples(data_rows: list[dict[str, Any]], widget_name: str, limit: int = 3) -> list[Any]:
    samples: list[Any] = []
    for row in data_rows:
        if widget_name in row:
            value = row.get(widget_name)
            if value is not None:
                samples.append(value)
        if len(samples) >= limit:
            break
    return samples


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = _parse_args()
    api_key = _require(args.api_key, "JIANDAOYUN_API_KEY / --api-key")
    app_id = _require(args.app_id, "JIANDAOYUN_APP_ID / --app-id")
    entry_id = _require(args.entry_id, "CUSTOMER_MAIN_ENTRY_ID / --entry-id")
    sample_limit = max(1, min(args.sample_limit, 20))

    client = JiandaoyunClient(api_key=api_key)
    raw_widgets = await client.fetch_form_widgets(app_id=app_id, entry_id=entry_id)
    raw_data = await client.fetch_form_data_list(app_id=app_id, entry_id=entry_id, limit=sample_limit)

    widgets = raw_widgets.get("widgets", [])
    data_rows = raw_data.get("data", [])

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    widgets_path = output_dir / "customer_main_widgets.json"
    sample_data_path = output_dir / "customer_main_data_sample.json"
    report_path = output_dir / "customer_main_snapshot_report.md"

    widgets_path.write_text(json.dumps(raw_widgets, ensure_ascii=False, indent=2), encoding="utf-8")
    sample_data_path.write_text(json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8")

    subform_widgets = [w for w in widgets if w.get("type") == "subform"]
    lookup_widgets = [w for w in widgets if w.get("type") == "lookup"]

    lines: list[str] = [
        "# 客户主表结构与数据采样报告",
        "",
        f"- 拉取时间(UTC): `{datetime.now(timezone.utc).isoformat()}`",
        f"- app_id: `{app_id}`",
        f"- customer_main_entry_id: `{entry_id}`",
        f"- 字段总数: `{len(widgets)}`",
        f"- 采样数据条数: `{len(data_rows)}`",
        f"- subform 字段数: `{len(subform_widgets)}`",
        f"- lookup 字段数: `{len(lookup_widgets)}`",
        "",
        "## 字段清单",
        "",
        "| 字段ID(widget name) | 字段名(label) | 类型(type) | 子字段 |",
        "| --- | --- | --- | --- |",
    ]
    for widget in widgets:
        lines.append(
            f"| `{widget.get('name', '-')}` | {widget.get('label', '-')} | "
            f"`{widget.get('type', '-')}` | {_subfields_text(widget)} |"
        )

    lines.extend(
        [
            "",
            "## 重点字段（subform / lookup）真实值示例",
            "",
            "> 下面展示真实数据中的字段值格式，便于确认写入语义。",
            "",
        ]
    )
    focus_widgets = subform_widgets + lookup_widgets
    if not focus_widgets:
        lines.append("- 未发现 subform/lookup 字段。")
    else:
        for widget in focus_widgets:
            samples = _extract_field_samples(data_rows, widget.get("name", ""), limit=3)
            lines.append(f"### {widget.get('label', '-') } (`{widget.get('name', '-')}`, `{widget.get('type', '-')}`)")
            if not samples:
                lines.append("- 采样范围内无非空值。")
            else:
                for idx, sample in enumerate(samples, start=1):
                    lines.append(f"- 样例 {idx}: `{json.dumps(sample, ensure_ascii=False)}`")
            lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    print("完成：客户主表结构 + 数据采样")
    print(f"- {widgets_path}")
    print(f"- {sample_data_path}")
    print(f"- {report_path}")


if __name__ == "__main__":
    asyncio.run(main())

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
    parser = argparse.ArgumentParser(description="Fetch Jiandaoyun form widget structures.")
    parser.add_argument("--api-key", default=os.getenv("JIANDAOYUN_API_KEY", ""))
    parser.add_argument("--app-id", default=os.getenv("JIANDAOYUN_APP_ID", ""))
    parser.add_argument("--yuqi-entry-id", default=os.getenv("FORM_ENTRY_ID_YUQI", ""))
    parser.add_argument("--changjing-entry-id", default=os.getenv("FORM_ENTRY_ID_CHANGJING", ""))
    return parser.parse_args()


def _require(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"缺少参数: {name}")
    return normalized


def _subfield_summary(widget: dict[str, Any]) -> str:
    if widget.get("type") != "subform":
        return "-"
    parts: list[str] = []
    for item in widget.get("items", []) or []:
        parts.append(f"{item.get('label', '-')}" f"({item.get('type', '-')})")
    return "-> " + ", ".join(parts) if parts else "-> (empty)"


def _print_table(form_name: str, entry_id: str, widgets: list[dict[str, Any]]) -> None:
    print(f"\n========== 表单：{form_name} (entry_id: {entry_id}) ==========")
    print("序号 | 字段ID | 字段名 | 类型 | 子字段")
    for idx, widget in enumerate(widgets, start=1):
        print(
            f"{idx} | {widget.get('name', '-')} | {widget.get('label', '-')} | "
            f"{widget.get('type', '-')} | {_subfield_summary(widget)}"
        )


def _build_markdown(form_name: str, entry_id: str, widgets: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append(f"## 表单：{form_name}")
    lines.append("")
    lines.append(f"- entry_id: `{entry_id}`")
    lines.append(f"- 字段总数: `{len(widgets)}`")
    lines.append("")
    lines.append("| 字段ID(widget name) | 字段名(label) | 类型(type) | 是否子表单 | 子字段列表 | 关注标记 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for widget in widgets:
        widget_type = str(widget.get("type", "-"))
        is_subform = "是" if widget_type == "subform" else "否"
        marker = ""
        if widget_type == "subform":
            marker = "subform"
        elif widget_type == "lookup":
            marker = "lookup"
        subfields = (
            ", ".join(f"{item.get('label', '-')}" f"({item.get('type', '-')})" for item in (widget.get("items") or []))
            if widget_type == "subform"
            else "-"
        )
        lines.append(
            f"| `{widget.get('name', '-')}` | {widget.get('label', '-')} | `{widget_type}` | "
            f"{is_subform} | {subfields} | **{marker or '-'}** |"
        )
    lines.append("")
    return "\n".join(lines)


async def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = _parse_args()
    api_key = _require(args.api_key, "JIANDAOYUN_API_KEY / --api-key")
    app_id = _require(args.app_id, "JIANDAOYUN_APP_ID / --app-id")
    yuqi_entry_id = _require(args.yuqi_entry_id, "FORM_ENTRY_ID_YUQI / --yuqi-entry-id")
    changjing_entry_id = _require(args.changjing_entry_id, "FORM_ENTRY_ID_CHANGJING / --changjing-entry-id")

    client = JiandaoyunClient(api_key=api_key)
    yuqi_raw = await client.fetch_form_widgets(app_id=app_id, entry_id=yuqi_entry_id)
    changjing_raw = await client.fetch_form_widgets(app_id=app_id, entry_id=changjing_entry_id)

    yuqi_widgets = yuqi_raw.get("widgets", [])
    changjing_widgets = changjing_raw.get("widgets", [])

    _print_table("预期", yuqi_entry_id, yuqi_widgets)
    _print_table("场景", changjing_entry_id, changjing_widgets)

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    yuqi_json_path = output_dir / "form_yuqi_widgets.json"
    changjing_json_path = output_dir / "form_changjing_widgets.json"
    report_path = output_dir / "form_structure_report.md"

    yuqi_json_path.write_text(json.dumps(yuqi_raw, ensure_ascii=False, indent=2), encoding="utf-8")
    changjing_json_path.write_text(json.dumps(changjing_raw, ensure_ascii=False, indent=2), encoding="utf-8")

    pulled_at = datetime.now(timezone.utc).isoformat()
    report_sections = [
        "# 简道云表单字段结构报告",
        "",
        f"- 拉取时间(UTC): `{pulled_at}`",
        f"- 应用ID: `{app_id}`",
        f"- 预期表字段数: `{len(yuqi_widgets)}`",
        f"- 场景表字段数: `{len(changjing_widgets)}`",
        "",
        "> 重点关注 `subform`（子表单）和 `lookup`（关联数据）字段。",
        "",
        _build_markdown("预期", yuqi_entry_id, yuqi_widgets),
        _build_markdown("场景", changjing_entry_id, changjing_widgets),
    ]
    report_path.write_text("\n".join(report_sections), encoding="utf-8")

    print("\n输出文件：")
    print(f"- {yuqi_json_path}")
    print(f"- {changjing_json_path}")
    print(f"- {report_path}")


if __name__ == "__main__":
    asyncio.run(main())

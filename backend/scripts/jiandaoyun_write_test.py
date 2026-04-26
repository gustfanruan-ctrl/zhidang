from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


API_BASE = "https://api.jiandaoyun.com/api/v5"
ENTRY_SCENE = "69e836fd206c3a2d9ffb5cf4"
ENTRY_YUQI = "69e836f10bc8756eea476a1f"
YUQI_SUBFORM_WIDGET = "_widget_1773297739599"
YUQI_WIDGETS_PATH = Path(__file__).resolve().parent / "output" / "form_yuqi_widgets.json"
RESULT_PATH = Path(__file__).resolve().parent / "output" / "write_test_result.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def unwrap_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def wrap_widget_value(raw_value: Any) -> dict[str, Any]:
    return {"value": raw_value}


def deep_extract_plain_subform_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    extracted: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item: dict[str, Any] = {}
        for key, value in row.items():
            if key == "_id":
                item[key] = value
                continue
            item[key] = unwrap_value(value)
        extracted.append(item)
    return extracted


async def post_json(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    endpoint: str,
    body: dict[str, Any],
) -> tuple[int, dict[str, Any], str]:
    response = await client.post(f"{API_BASE}{endpoint}", headers=headers, json=body)
    text = response.text
    try:
        data = response.json()
    except Exception:
        data = {}
    return response.status_code, data, text


def safe_result(
    passed: bool,
    **kwargs: Any,
) -> dict[str, Any]:
    payload = {"passed": passed}
    payload.update(kwargs)
    return payload


def build_subform_test_row(
    subform_items: list[dict[str, Any]],
) -> dict[str, Any]:
    text_widget = None
    datetime_widget = None
    for item in subform_items:
        if item.get("type") in {"text", "textarea"} and not text_widget:
            text_widget = item.get("name")
        if item.get("type") == "datetime" and not datetime_widget:
            datetime_widget = item.get("name")
    if text_widget and datetime_widget:
        return {
            text_widget: "zhidang_subform_test",
            datetime_widget: "2026-04-24T00:00:00Z",
        }

    if len(subform_items) < 2:
        raise ValueError("subform 子字段不足 2 个，无法执行追加测试")
    first = subform_items[0]
    second = subform_items[1]
    first_name = first.get("name")
    second_name = second.get("name")
    if not first_name or not second_name:
        raise ValueError("subform 前两个子字段缺少 name")

    first_type = str(first.get("type") or "")
    second_type = str(second.get("type") or "")
    first_value: Any = "zhidang_subform_test_fallback"
    second_value: Any = "zhidang_subform_test_fallback_2"
    if first_type == "datetime":
        first_value = "2026-04-24T00:00:00Z"
    if second_type == "datetime":
        second_value = "2026-04-24T00:00:00Z"
    return {first_name: first_value, second_name: second_value}


async def main() -> None:
    api_key = (os.getenv("JIANDAOYUN_API_KEY") or "").strip()
    app_id = (os.getenv("JIANDAOYUN_APP_ID") or "5dcbcb63d6e30c000692464e").strip()
    if not api_key:
        raise SystemExit("缺少环境变量 JIANDAOYUN_API_KEY")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    results: dict[str, dict[str, Any]] = {}
    test_data_id: str | None = None
    yuqi_data_id: str | None = None
    original_subform: list[dict[str, Any]] | None = None
    subform_items: list[dict[str, Any]] = []
    subform_test_row: dict[str, Any] | None = None

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        # Step 1 - create
        try:
            body = {
                "app_id": app_id,
                "entry_id": ENTRY_SCENE,
                "data": {
                    "title": {"value": "zhidang_write_test_20260424"},
                    "_widget_1760081332280": {"value": "test_marker"},
                },
            }
            status, data, raw = await post_json(client, headers, "/app/entry/data/create", body)
            if status == 200 and (data.get("data") or {}).get("_id"):
                test_data_id = data["data"]["_id"]
                results["step1_create"] = safe_result(True, status_code=status, data_id=test_data_id, error=None)
            else:
                results["step1_create"] = safe_result(False, status_code=status, data_id=None, error=raw)
        except Exception as exc:
            results["step1_create"] = safe_result(False, status_code=None, data_id=None, error=str(exc))

        # Step 2 - read verify
        try:
            if not test_data_id:
                raise RuntimeError("step1 未创建 data_id")
            body = {"app_id": app_id, "entry_id": ENTRY_SCENE, "data_id": test_data_id}
            status, data, raw = await post_json(client, headers, "/app/entry/data/get", body)
            actual = ((data.get("data") or {}).get("title"))
            passed = status == 200 and actual == "zhidang_write_test_20260424"
            results["step2_read"] = safe_result(
                passed,
                status_code=status,
                verified_field="title",
                expected="zhidang_write_test_20260424",
                actual=actual,
                error=None if passed else raw,
            )
        except Exception as exc:
            results["step2_read"] = safe_result(
                False,
                status_code=None,
                verified_field="title",
                expected="zhidang_write_test_20260424",
                actual=None,
                error=str(exc),
            )

        # Step 3 - update verify
        try:
            if not test_data_id:
                raise RuntimeError("step1 未创建 data_id")
            body = {
                "app_id": app_id,
                "entry_id": ENTRY_SCENE,
                "data_id": test_data_id,
                "data": {
                    "title": {"value": "zhidang_write_test_updated"},
                },
            }
            status, _, raw = await post_json(client, headers, "/app/entry/data/update", body)
            body_get = {"app_id": app_id, "entry_id": ENTRY_SCENE, "data_id": test_data_id}
            _, data_get, _ = await post_json(client, headers, "/app/entry/data/get", body_get)
            actual = ((data_get.get("data") or {}).get("title"))
            passed = status == 200 and actual == "zhidang_write_test_updated"
            results["step3_update"] = safe_result(
                passed,
                status_code=status,
                verified_field="title",
                expected="zhidang_write_test_updated",
                actual=actual,
                error=None if passed else raw,
            )
        except Exception as exc:
            results["step3_update"] = safe_result(
                False,
                status_code=None,
                verified_field="title",
                expected="zhidang_write_test_updated",
                actual=None,
                error=str(exc),
            )

        # Step 4 - delete (always try cleanup)
        try:
            if not test_data_id:
                raise RuntimeError("step1 未创建 data_id")
            body = {"app_id": app_id, "entry_id": ENTRY_SCENE, "data_id": test_data_id}
            status, data, raw = await post_json(client, headers, "/app/entry/data/delete", body)
            passed = status == 200 and data.get("status") == "success"
            results["step4_delete"] = safe_result(
                passed,
                status_code=status,
                error=None if passed else raw,
            )
        except Exception as exc:
            results["step4_delete"] = safe_result(False, status_code=None, error=str(exc))

        # Step 5 - locate yuqi record with non-empty subform
        step5_skip_reason = None
        try:
            if not YUQI_WIDGETS_PATH.exists():
                raise FileNotFoundError(f"找不到 {YUQI_WIDGETS_PATH}")
            widgets_doc = json.loads(YUQI_WIDGETS_PATH.read_text(encoding="utf-8"))
            widgets = widgets_doc.get("widgets", []) if isinstance(widgets_doc, dict) else []
            target_widget = next((w for w in widgets if w.get("name") == YUQI_SUBFORM_WIDGET), None)
            if not target_widget:
                raise RuntimeError(f"找不到 subform widget {YUQI_SUBFORM_WIDGET}")
            subform_items = target_widget.get("items", []) or []
            subform_test_row = build_subform_test_row(subform_items)

            cursor = None
            found = None
            for _ in range(10):
                body = {"app_id": app_id, "entry_id": ENTRY_YUQI, "limit": 5}
                if cursor:
                    body["data_id"] = cursor
                status, data, raw = await post_json(client, headers, "/app/entry/data/list", body)
                if status != 200:
                    raise RuntimeError(f"data/list 失败: {status} {raw}")
                rows = data.get("data", []) or []
                if not rows:
                    break
                for row in rows:
                    arr = row.get(YUQI_SUBFORM_WIDGET) or []
                    if isinstance(arr, list) and len(arr) > 0:
                        found = row
                        break
                if found:
                    break
                cursor = rows[-1].get("_id")
                if not cursor:
                    break

            if not found:
                raise RuntimeError("未找到带 subform 数据的预期记录")
            yuqi_data_id = found.get("_id")
            original_subform = deep_extract_plain_subform_rows(found.get(YUQI_SUBFORM_WIDGET) or [])
        except Exception as exc:
            step5_skip_reason = str(exc)

        # Step 5a - subform append (replace full array)
        if step5_skip_reason:
            results["step5a_subform_append"] = safe_result(
                False,
                skipped=True,
                reason=step5_skip_reason,
                original_rows=0,
                after_rows=0,
                old_rows_intact=False,
            )
        else:
            try:
                assert yuqi_data_id is not None
                assert original_subform is not None
                assert subform_test_row is not None
                merged_rows = list(original_subform) + [subform_test_row]
                wrapped_rows = []
                for row in merged_rows:
                    wrapped_row = {}
                    for k, v in row.items():
                        if k == "_id":
                            wrapped_row[k] = v
                        else:
                            wrapped_row[k] = wrap_widget_value(v)
                    wrapped_rows.append(wrapped_row)
                body = {
                    "app_id": app_id,
                    "entry_id": ENTRY_YUQI,
                    "data_id": yuqi_data_id,
                    "data": {
                        YUQI_SUBFORM_WIDGET: {
                            "value": wrapped_rows,
                        }
                    },
                }
                status_upd, _, raw_upd = await post_json(client, headers, "/app/entry/data/update", body)
                body_get = {"app_id": app_id, "entry_id": ENTRY_YUQI, "data_id": yuqi_data_id}
                _, data_get, _ = await post_json(client, headers, "/app/entry/data/get", body_get)
                after_rows_raw = data_get.get("data", {}).get(YUQI_SUBFORM_WIDGET) or []
                after_rows = deep_extract_plain_subform_rows(after_rows_raw)
                old_rows_intact = after_rows[: len(original_subform)] == original_subform
                passed = (
                    status_upd == 200
                    and len(after_rows) == len(original_subform) + 1
                    and old_rows_intact
                )
                results["step5a_subform_append"] = safe_result(
                    passed,
                    status_code=status_upd,
                    original_rows=len(original_subform),
                    after_rows=len(after_rows),
                    old_rows_intact=old_rows_intact,
                    error=None if passed else raw_upd,
                )
            except Exception as exc:
                results["step5a_subform_append"] = safe_result(
                    False,
                    status_code=None,
                    original_rows=len(original_subform or []),
                    after_rows=0,
                    old_rows_intact=False,
                    error=str(exc),
                )

        # Step 5b - restore original subform (always try cleanup when step5 had context)
        if step5_skip_reason:
            results["step5b_subform_restore"] = safe_result(
                False,
                skipped=True,
                reason=step5_skip_reason,
                restored_rows=0,
            )
        else:
            try:
                assert yuqi_data_id is not None
                assert original_subform is not None
                wrapped_rows = []
                for row in original_subform:
                    wrapped_row = {}
                    for k, v in row.items():
                        if k == "_id":
                            wrapped_row[k] = v
                        else:
                            wrapped_row[k] = wrap_widget_value(v)
                    wrapped_rows.append(wrapped_row)
                body_restore = {
                    "app_id": app_id,
                    "entry_id": ENTRY_YUQI,
                    "data_id": yuqi_data_id,
                    "data": {
                        YUQI_SUBFORM_WIDGET: {
                            "value": wrapped_rows,
                        }
                    },
                }
                status_restore, _, raw_restore = await post_json(client, headers, "/app/entry/data/update", body_restore)
                body_get = {"app_id": app_id, "entry_id": ENTRY_YUQI, "data_id": yuqi_data_id}
                _, data_get, _ = await post_json(client, headers, "/app/entry/data/get", body_get)
                after_restore = deep_extract_plain_subform_rows(data_get.get("data", {}).get(YUQI_SUBFORM_WIDGET) or [])
                passed = status_restore == 200 and after_restore == original_subform
                results["step5b_subform_restore"] = safe_result(
                    passed,
                    status_code=status_restore,
                    restored_rows=len(after_restore),
                    error=None if passed else raw_restore,
                )
            except Exception as exc:
                results["step5b_subform_restore"] = safe_result(
                    False,
                    status_code=None,
                    restored_rows=0,
                    error=str(exc),
                )

    passed_count = sum(1 for item in results.values() if item.get("passed"))
    total_count = len(results)
    summary = f"{passed_count}/{total_count} passed" if passed_count == total_count else f"{passed_count}/{total_count} passed, see errors"
    conclusion = {
        "write_permission": bool(results.get("step1_create", {}).get("passed")),
        "update_permission": bool(results.get("step3_update", {}).get("passed")),
        "delete_permission": bool(results.get("step4_delete", {}).get("passed")),
        "subform_mode": "replace_full_array" if results.get("step5a_subform_append", {}).get("passed") else "unknown",
    }

    payload = {
        "test_time": now_iso(),
        "results": results,
        "summary": summary,
        "conclusion": conclusion,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Jiandaoyun write test completed.")
    print(f"Summary: {summary}")
    print(f"Conclusion: {json.dumps(conclusion, ensure_ascii=False)}")
    print(f"Result file: {RESULT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())


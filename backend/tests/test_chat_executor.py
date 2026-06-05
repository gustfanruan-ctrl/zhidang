import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chat_executor import (  # noqa: E402
    ChatPayloadValidationError,
    build_preview_text,
    build_jiandaoyun_payload,
    normalize_chat_tool_input,
    normalize_expectation_status_value,
)


def _form_config() -> dict:
    return {
        "field_mapping": {
            "预期状态": {"widget": "yuqi_status"},
            "预期简述": {"widget": "detail_brief"},
        },
        "lookup_customer": {"widget": "relation"},
    }


def test_normalize_expectation_status_value_keeps_canonical_values():
    assert normalize_expectation_status_value("未启动") == "未启动"
    assert normalize_expectation_status_value("进行中") == "进行中"
    assert normalize_expectation_status_value("已达成") == "已达成"
    assert normalize_expectation_status_value("已作废") == "已作废"


def test_build_jiandaoyun_payload_maps_completed_status_to_yidacheng():
    payload = build_jiandaoyun_payload(
        {
            "company_id": "company-1",
            "fields": {
                "预期状态": "已完成",
                "预期简述": "示例预期",
            },
        },
        _form_config(),
    )

    assert payload["yuqi_status"] == {"value": "已达成"}
    assert payload["detail_brief"] == {"value": "示例预期"}
    assert payload["relation"] == {"value": "company-1"}


def test_chat_expectation_create_payload_includes_relation_com_name_and_com_id():
    payload = build_jiandaoyun_payload(
        {
            "company_id": "company-1",
            "target_form": "预期表",
            "customer_com_id": "crm-1",
            "customer_com_name": "示例客户",
            "fields": {
                "预期简述": "示例预期",
            },
        },
        _form_config(),
    )

    assert payload["relation"] == {"value": "company-1"}
    assert payload["com_id"] == {"value": "crm-1"}
    assert payload["com_name"] == {"value": "示例客户"}


def test_chat_scene_create_payload_includes_customer_helper_fields():
    payload = build_jiandaoyun_payload(
        {
            "company_id": "company-1",
            "target_form": "场景表",
            "customer_com_id": "crm-1",
            "customer_com_name": "示例客户",
            "related_yuqi_id": "yuqi-1",
            "fields": {},
        },
        {
            "field_mapping": {},
            "lookup_customer": {"widget": "_widget_1737335801798"},
            "lookup_yuqi": {"widget": "_widget_1751435602563"},
            "customer_name_widget": "_widget_1743993204408",
        },
    )

    assert payload["_widget_1737335801798"] == {"value": "company-1"}
    assert payload["com_id"] == {"value": "crm-1"}
    assert payload["_widget_1743993204408"] == {"value": "示例客户"}
    assert payload["_widget_1751435602563"] == {"value": "yuqi-1"}


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("完成", "已达成"),
        ("已结束", "已达成"),
        ("结束", "已达成"),
        ("作废", "已作废"),
        ("未开始", "未启动"),
        ("处理中", "进行中"),
    ],
)
def test_normalize_expectation_status_value_maps_aliases(raw_value: str, expected: str):
    assert normalize_expectation_status_value(raw_value) == expected


def test_build_jiandaoyun_payload_rejects_unknown_expectation_status():
    with pytest.raises(ChatPayloadValidationError, match="预期状态 仅支持"):
        build_jiandaoyun_payload(
            {
                "company_id": "company-1",
                "fields": {"预期状态": "待确认"},
            },
            _form_config(),
        )


def test_build_jiandaoyun_payload_rejects_blank_expectation_status():
    with pytest.raises(ChatPayloadValidationError, match="不能为空"):
        build_jiandaoyun_payload(
            {
                "company_id": "company-1",
                "fields": {"预期状态": ""},
            },
            _form_config(),
        )


def test_normalize_chat_tool_input_maps_expectation_status_alias_for_preview_and_write():
    tool_input = normalize_chat_tool_input(
        {
            "company_id": "company-1",
            "target_form": "预期表",
            "data_id": "exp-1",
            "fields": {
                "预期简述": "为一线销售提供移动端数据查看工具",
                "预期状态": "已关闭",
            },
        }
    )

    assert tool_input["fields"]["预期状态"] == "已作废"


def test_build_preview_text_uses_canonical_expectation_status():
    preview = build_preview_text(
        "update_customer_record",
        {
            "company_id": "company-1",
            "target_form": "预期表",
            "data_id": "exp-1",
            "fields": {
                "预期简述": "为一线销售提供移动端数据查看工具",
                "预期状态": "已关闭",
            },
        },
    )

    assert "已作废" in preview
    assert "已关闭" not in preview

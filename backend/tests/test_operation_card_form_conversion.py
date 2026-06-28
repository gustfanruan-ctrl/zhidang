import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import (  # noqa: E402
    _apply_operation_card_override,
    _refresh_operation_card_safety,
)


FORMS_CFG = {
    "预期表": {
        "field_mapping": {
            "预期简述": {"widget": "detail_brief", "safety": "writable"},
            "预期详情": {"widget": "detail", "safety": "writable"},
            "预期状态": {"widget": "yuqi_status", "safety": "writable"},
            "是否第一价值实现预期": {"widget": "_widget_1770346583096", "safety": "writable"},
        },
        "lookup_customer": {"widget": "relation"},
    },
    "场景表": {
        "field_mapping": {
            "场景标题": {"widget": "title", "safety": "writable"},
            "是否第一价值实现场景": {"widget": "_widget_1744337240628", "safety": "writable"},
            "业务诉求/痛点分析": {"widget": "solve_what_ques", "safety": "writable"},
            "核心指标&解决方案": {"widget": "solve_what_ans", "safety": "writable"},
            "价值量化": {"widget": "_widget_1773296816191", "safety": "writable"},
            "总结沉淀": {"widget": "_widget_1773296816192", "safety": "writable"},
            "成果应用方式": {"widget": "_widget_1737340360281", "safety": "writable"},
        },
        "lookup_customer": {"widget": "_widget_1737335801798"},
    },
}


def _by_field(card):
    return {item["field_name"]: item for item in card["change_items"]}


def test_expectation_card_converts_to_scene_fields_before_write():
    card = {
        "card_id": "card-1",
        "target_form": "预期表",
        "operation_type": "update",
        "data_id": "old-yuqi-id",
        "change_items": [
            {"field_name": "预期简述", "widget_name": "detail_brief", "new_value": "建设经营分析能力"},
            {"field_name": "预期详情", "widget_name": "detail", "new_value": "希望管理层看到核心指标"},
            {"field_name": "是否第一价值实现预期", "widget_name": "_widget_1770346583096", "new_value": "是"},
        ],
    }

    _apply_operation_card_override(card, {"target_form": "场景表"}, FORMS_CFG)
    _refresh_operation_card_safety(card, FORMS_CFG)

    fields = _by_field(card)
    assert card["target_form"] == "场景表"
    assert card["operation_type"] == "create"
    assert card["data_id"] is None
    assert set(fields) == {"场景标题", "业务诉求/痛点分析", "是否第一价值实现场景"}
    assert fields["场景标题"]["widget_name"] == "title"
    assert fields["场景标题"]["new_value"] == "建设经营分析能力"
    assert fields["业务诉求/痛点分析"]["widget_name"] == "solve_what_ques"
    assert card["safety_status"] == "writable"


def test_scene_card_converts_to_expectation_fields_before_write():
    card = {
        "card_id": "card-2",
        "target_form": "场景表",
        "operation_type": "update",
        "data_id": "old-scene-id",
        "related_yuqi_id": "yuqi-1",
        "change_items": [
            {"field_name": "场景标题", "widget_name": "title", "new_value": "支行风险画像"},
            {"field_name": "业务诉求/痛点分析", "widget_name": "solve_what_ques", "new_value": "支行监测分散"},
            {"field_name": "核心指标&解决方案", "widget_name": "solve_what_ans", "new_value": "统一风险看板"},
            {"field_name": "是否第一价值实现场景", "widget_name": "_widget_1744337240628", "new_value": "否"},
        ],
    }

    _apply_operation_card_override(card, {"target_form": "预期表"}, FORMS_CFG)
    _refresh_operation_card_safety(card, FORMS_CFG)

    fields = _by_field(card)
    assert card["target_form"] == "预期表"
    assert card["operation_type"] == "create"
    assert card["data_id"] is None
    assert "related_yuqi_id" not in card
    assert set(fields) == {"预期简述", "预期详情", "是否第一价值实现预期"}
    assert fields["预期简述"]["new_value"] == "支行风险画像"
    assert "【业务诉求/痛点分析】支行监测分散" in fields["预期详情"]["new_value"]
    assert "【核心指标&解决方案】统一风险看板" in fields["预期详情"]["new_value"]
    assert fields["是否第一价值实现预期"]["new_value"] == "否"
    assert card["safety_status"] == "writable"


def test_change_items_override_keeps_only_target_form_fields():
    card = {
        "card_id": "card-3",
        "target_form": "预期表",
        "operation_type": "create",
        "change_items": [
            {"field_name": "预期简述", "widget_name": "detail_brief", "new_value": "原预期"},
        ],
    }

    _apply_operation_card_override(
        card,
        {
            "target_form": "场景表",
            "change_items": [
                {"field_name": "预期简述", "widget_name": "detail_brief", "new_value": "旧字段应丢弃"},
                {"field_name": "场景标题", "widget_name": "title", "new_value": "新场景"},
            ],
        },
        FORMS_CFG,
    )
    _refresh_operation_card_safety(card, FORMS_CFG)

    fields = _by_field(card)
    assert set(fields) == {"场景标题"}
    assert fields["场景标题"]["widget_name"] == "title"
    assert fields["场景标题"]["new_value"] == "新场景"
    assert card["safety_status"] == "writable"

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tool_registry import _build_cards_by_string_match, exec_compare_ops_llm  # noqa: E402


EXPECTATION_FORM = "预期表"


def _expectation_form_cfg() -> dict:
    return {
        "field_mapping": {
            "预期简述": {"widget": "detail_brief"},
            "预期详情": {"widget": "detail"},
            "预期状态": {"widget": "yuqi_status"},
        },
        "lookup_customer": {"widget": "relation"},
    }


def _grouped_expectation(primary_value: str, detail_value: str, status_value: str = "进行中") -> dict:
    form_cfg = _expectation_form_cfg()
    return {
        "group-1": {
            "card_id": "card-1",
            "target_form": EXPECTATION_FORM,
            "form_cfg": form_cfg,
            "primary_field": "预期简述",
            "primary_widget": "detail_brief",
            "primary_value": primary_value,
            "lookup_widget": "relation",
            "confidence": 0.91,
            "source_quote": "会议纪要",
            "item_by_field": {
                "预期简述": {"widget_name": "detail_brief", "new_value": primary_value},
                "预期详情": {"widget_name": "detail", "new_value": detail_value},
                "预期状态": {"widget_name": "yuqi_status", "new_value": status_value},
            },
        }
    }


def _mapping() -> dict:
    return {EXPECTATION_FORM: _expectation_form_cfg()}


def _scene_form_cfg() -> dict:
    return {
        "field_mapping": {
            "场景标题": {"widget": "title"},
            "业务诉求/痛点分析": {"widget": "solve_what_ques"},
            "核心指标&解决方案": {"widget": "solve_what_ans"},
        },
        "lookup_customer": {"widget": "_widget_1737335801798"},
    }


def test_string_fallback_prefers_update_for_same_intent_paraphrase():
    grouped = _grouped_expectation(
        primary_value="优化审批流程提效",
        detail_value="当前审批流程太慢，需要缩短审批时长并提升响应效率",
    )
    existing_rows = {
        EXPECTATION_FORM: [
            {
                "_id": "exp-1",
                "detail_brief": "提升审批效率",
                "detail": "审批流太慢，影响内部响应速度",
                "yuqi_status": "未启动",
            }
        ]
    }

    cards = _build_cards_by_string_match(grouped, existing_rows, {"_id": "company-1"}, _mapping())

    assert len(cards) == 1
    assert cards[0]["operation_type"] == "update"
    assert cards[0]["data_id"] == "exp-1"


def test_string_fallback_skips_when_no_meaningful_delta():
    grouped = _grouped_expectation(
        primary_value="提升审批效率",
        detail_value="审批流程太慢，影响内部响应速度",
        status_value="进行中",
    )
    existing_rows = {
        EXPECTATION_FORM: [
            {
                "_id": "exp-1",
                "detail_brief": "提升审批效率",
                "detail": "审批流程太慢，影响内部响应速度",
                "yuqi_status": "进行中",
            }
        ]
    }

    cards = _build_cards_by_string_match(grouped, existing_rows, {"_id": "company-1"}, _mapping())

    assert cards == []


def test_string_fallback_keeps_create_for_new_intent():
    grouped = _grouped_expectation(
        primary_value="搭建经营分析看板",
        detail_value="希望按天查看门店经营指标并统一口径",
    )
    existing_rows = {
        EXPECTATION_FORM: [
            {
                "_id": "exp-1",
                "detail_brief": "提升审批效率",
                "detail": "审批流程太慢，影响内部响应速度",
                "yuqi_status": "未启动",
            }
        ]
    }

    cards = _build_cards_by_string_match(grouped, existing_rows, {"_id": "company-1"}, _mapping())

    assert len(cards) == 1
    assert cards[0]["operation_type"] == "create"
    assert cards[0]["data_id"] is None


@pytest.mark.asyncio
async def test_grouping_keeps_scene_details_when_titles_arrive_before_bodies():
    params = {
        "extracted_facts": [
            {
                "field_name": "预期简述",
                "value": "实现AI数据分析能力与本地智能体平台集成",
                "confidence": 0.9,
                "source_quote": "预期引用",
                "target_form": "预期表",
            },
            {
                "field_name": "场景标题",
                "value": "本地智能体平台集成AI数据分析能力",
                "confidence": 0.9,
                "source_quote": "连接起来",
                "target_form": "场景表",
            },
            {
                "field_name": "场景标题",
                "value": "业务用户自助生成数据分析报告",
                "confidence": 0.9,
                "source_quote": "通过对话方式",
                "target_form": "场景表",
            },
            {
                "field_name": "业务诉求/痛点分析",
                "value": "场景一的问题描述",
                "confidence": 0.85,
                "source_quote": "连接起来，集中式执行有瓶颈",
                "target_form": "场景表",
            },
            {
                "field_name": "核心指标&解决方案",
                "value": "场景一的解决方案",
                "confidence": 0.85,
                "source_quote": "连接起来，用 MCP/API 打通",
                "target_form": "场景表",
            },
            {
                "field_name": "业务诉求/痛点分析",
                "value": "场景二的问题描述",
                "confidence": 0.85,
                "source_quote": "通过对话方式，业务用户缺少能力",
                "target_form": "场景表",
            },
            {
                "field_name": "核心指标&解决方案",
                "value": "场景二的解决方案",
                "confidence": 0.85,
                "source_quote": "通过对话方式，自动生成报告",
                "target_form": "场景表",
            },
        ],
        "existing_profile": {"_id": "company-1", "yuqi": [], "changjing": []},
        "runtime_cfg": {"mapping": {"forms": {"预期表": _expectation_form_cfg(), "场景表": _scene_form_cfg()}}},
        "llm_cfg": {},
    }

    result = await exec_compare_ops_llm(params)
    scene_cards = [card for card in result["operation_cards"] if card["target_form"] == "场景表"]

    assert len(scene_cards) == 2
    by_title = {
        next(item["new_value"] for item in card["change_items"] if item["field_name"] == "场景标题"): card
        for card in scene_cards
    }
    first_fields = {item["field_name"]: item["new_value"] for item in by_title["本地智能体平台集成AI数据分析能力"]["change_items"]}
    second_fields = {item["field_name"]: item["new_value"] for item in by_title["业务用户自助生成数据分析报告"]["change_items"]}

    assert first_fields["业务诉求/痛点分析"] == "场景一的问题描述"
    assert first_fields["核心指标&解决方案"] == "场景一的解决方案"
    assert second_fields["业务诉求/痛点分析"] == "场景二的问题描述"
    assert second_fields["核心指标&解决方案"] == "场景二的解决方案"

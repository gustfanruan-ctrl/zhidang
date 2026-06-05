import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import _build_missing_field_prompt  # noqa: E402


def test_expectation_create_requires_brief_and_detail():
    prompt = _build_missing_field_prompt(
        "create_customer_record",
        {
            "target_form": "预期表",
            "fields": {
                "预期简述": "提升数据分析效率",
            },
        },
        {
            "field_mapping": {
                "预期简述": {"widget": "detail_brief"},
                "预期详情": {"widget": "detail"},
            }
        },
    )

    assert prompt is not None
    assert "预期详情" in prompt


def test_scene_create_requires_related_yuqi_and_core_fields():
    prompt = _build_missing_field_prompt(
        "create_customer_record",
        {
            "target_form": "场景表",
            "fields": {
                "场景标题": "经营分析看板",
                "业务诉求/痛点分析": "需要补充",
            },
        },
        {
            "field_mapping": {
                "场景标题": {"widget": "title"},
                "业务诉求/痛点分析": {"widget": "solve_what_ques"},
                "核心指标&解决方案": {"widget": "solve_what_ans"},
            }
        },
    )

    assert prompt is not None
    assert "业务诉求/痛点分析" in prompt
    assert "核心指标&解决方案" in prompt
    assert "关联预期" in prompt


def test_complete_scene_create_does_not_get_blocked():
    prompt = _build_missing_field_prompt(
        "create_customer_record",
        {
            "target_form": "场景表",
            "related_yuqi_id": "yuqi-1",
            "fields": {
                "场景标题": "经营分析看板",
                "业务诉求/痛点分析": "当前靠 Excel 汇总，口径不统一。",
                "核心指标&解决方案": "统一口径后按日推送经营指标。",
            },
        },
        {
            "field_mapping": {
                "场景标题": {"widget": "title"},
                "业务诉求/痛点分析": {"widget": "solve_what_ques"},
                "核心指标&解决方案": {"widget": "solve_what_ans"},
            }
        },
    )

    assert prompt is None

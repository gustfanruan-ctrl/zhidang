import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tool_registry import _resolve_field_rule  # noqa: E402


def _scene_form_cfg() -> dict:
    return {
        "field_mapping": {
            "场景标题": {"widget": "title"},
            "是否第一价值实现场景": {"widget": "_widget_1744337240628"},
            "业务诉求/痛点分析": {"widget": "solve_what_ques"},
            "核心指标&解决方案": {"widget": "solve_what_ans"},
            "价值量化": {"widget": "_widget_1773296816191"},
            "总结沉淀": {"widget": "_widget_1773296816192"},
            "成果应用方式": {"widget": "_widget_1737340360281"},
        }
    }


def test_scene_field_aliases_map_old_labels_to_live_schema():
    form_cfg = _scene_form_cfg()

    canonical, rule = _resolve_field_rule("场景表", "解决什么问题", form_cfg)
    assert canonical == "业务诉求/痛点分析"
    assert rule["widget"] == "solve_what_ques"

    canonical, rule = _resolve_field_rule("场景表", "怎样解决", form_cfg)
    assert canonical == "核心指标&解决方案"
    assert rule["widget"] == "solve_what_ans"


def test_scene_field_aliases_map_extra_live_widgets():
    form_cfg = _scene_form_cfg()

    canonical, rule = _resolve_field_rule("场景表", "_widget_1773296816191", form_cfg)
    assert canonical == "价值量化"
    assert rule["widget"] == "_widget_1773296816191"

    canonical, rule = _resolve_field_rule("场景表", "成果应用方式", form_cfg)
    assert canonical == "成果应用方式"
    assert rule["widget"] == "_widget_1737340360281"

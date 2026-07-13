import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.power_map_service import (  # noqa: E402
    _POWER_MAP_CLEAN_RAW_OK,
    _parse_power_map_intent,
    _validate_power_map_cleaned_text,
)


LONG_HAIYOU_RAW = """
主体单位为海洋石油工程股份有限公司（海油工程），中国海洋石油集团控股的上市公司，
国内唯一集设计、采购、建造、海上安装、调试维修、LNG、海上风电、炼化于一体的 EPCI 总承包商。
这段背景只是介绍企业，不应全部进入图。

层级关系为：中国海洋石油集团 → 海油工程。海油工程下设机关部室、设计板块、采购板块、建造板块、
安装板块、运维/项目管理板块、特种/新能源板块。机关部室下有人事、财务、党群、科技信息部。
设计板块下设设计院，设计院下设上海分部和深圳分部。采购板块下设采办共享中心。
建造板块下设天津智能制造基地、中海福陆、青岛子公司、塘沽基地。
安装板块下设安装分公司和深圳子公司。运维/项目管理板块下设工程项目分公司和海油工程国际有限公司。

信息化条线为：分管领导 → 科技信息部 → 研发中心 → ITC。
关键人员：吕亚平是研发中心领导；你本人是 ITC 副职/技术负责人；刘墨林是科技信息部联系人。
注意：刘墨林在机关侧，你本人在执行侧。天津中车不是天津智能制造基地，不要混淆。
"""


def test_cleaning_contract_accepts_compact_json_that_feeds_intent_parser():
    cleaned = {
        "g": "建立海油工程组织层级和信息化条线",
        "d": [
            ["中国海洋石油集团", "", "group"],
            ["海油工程", "中国海洋石油集团", "company"],
            ["机关部室", "海油工程", "department"],
            ["科技信息部", "机关部室", "department"],
            ["研发中心", "科技信息部", "department"],
            ["ITC", "研发中心", "team"],
            ["设计板块", "海油工程", "department"],
            ["设计院", "设计板块", "department"],
            ["上海分部", "设计院", "team"],
            ["深圳分部", "设计院", "team"],
        ],
        "p": [
            ["分管领导", "信息化分管领导", "海油工程"],
            ["吕亚平", "研发中心领导", "研发中心"],
            ["你本人", "ITC 副职/技术负责人", "ITC"],
            ["刘墨林", "科技信息部联系人", "科技信息部"],
        ],
        "e": [
            ["刘墨林", "分管领导", "reports_to"],
            ["吕亚平", "刘墨林", "reports_to"],
            ["你本人", "吕亚平", "reports_to"],
        ],
        "c": ["天津中车不是天津智能制造基地"],
    }
    cleaned_text = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))

    accepted = _validate_power_map_cleaned_text(
        raw_text=LONG_HAIYOU_RAW * 5,
        cleaned_text=cleaned_text,
        session_id="test",
    )
    intent = _parse_power_map_intent(accepted)

    assert accepted
    assert intent.goal == "建立海油工程组织层级和信息化条线"
    assert {dept.name for dept in intent.departments} >= {"中国海洋石油集团", "海油工程", "科技信息部", "ITC"}
    assert {person.name for person in intent.people} >= {"吕亚平", "你本人", "刘墨林"}
    assert ("你本人", "吕亚平") in {(edge.source, edge.target) for edge in intent.report_edges}


def test_cleaning_contract_accepts_compact_dict_rows_with_closed_references():
    cleaned = {
        "g": "建立客户成功三级组织",
        "d": [
            {"name": "华东公司", "parent": "", "kind": "company"},
            {"name": "客户成功部", "parent": "华东公司", "kind": "department"},
            {"name": "KA小组", "parent": "客户成功部", "kind": "team"},
        ],
        "p": [
            {"name": "客户成功负责人", "title": "负责人", "department": "客户成功部"},
            {"name": "KA组长", "title": "组长", "department": "KA小组"},
        ],
        "e": [
            {"source": "KA组长", "target": "客户成功负责人", "relation": "reports_to"},
        ],
    }

    accepted = _validate_power_map_cleaned_text(
        raw_text=("客户成功背景说明" * 120) + "华东公司下设客户成功部，客户成功部下设KA小组。",
        cleaned_text=json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")),
        session_id="test",
    )
    intent = _parse_power_map_intent(accepted)

    assert accepted
    assert [(dept.name, dept.parent) for dept in intent.departments] == [
        ("华东公司", ""),
        ("客户成功部", "华东公司"),
        ("KA小组", "客户成功部"),
    ]
    assert [(person.name, person.parent) for person in intent.people] == [
        ("客户成功负责人", "客户成功部"),
        ("KA组长", "KA小组"),
    ]
    assert [(edge.source, edge.target) for edge in intent.report_edges] == [
        ("KA组长", "客户成功负责人")
    ]


def test_cleaning_contract_infers_missing_person_edge_endpoint_from_compact_rows():
    cleaned = {
        "g": "建立海油工程信息化条线",
        "d": [
            ["海油工程", "", "company"],
            ["科技信息部", "海油工程", "department"],
        ],
        "p": [
            ["刘墨林", "科技信息部联系人", "科技信息部"],
        ],
        "e": [
            ["刘墨林", "分管领导", "reports_to"],
        ],
    }

    accepted = _validate_power_map_cleaned_text(
        raw_text=LONG_HAIYOU_RAW * 5,
        cleaned_text=json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")),
        session_id="test",
    )
    intent = _parse_power_map_intent(accepted)

    assert accepted
    assert {person.name for person in intent.people} >= {"刘墨林", "分管领导"}
    assert ("刘墨林", "分管领导") in {(edge.source, edge.target) for edge in intent.report_edges}


def test_cleaning_contract_rejects_compact_department_edge_endpoint_missing_from_nodes():
    cleaned = {
        "g": "建立海油工程信息化条线",
        "d": [
            ["海油工程", "", "company"],
        ],
        "p": [
            ["刘墨林", "科技信息部联系人", "海油工程"],
        ],
        "e": [
            ["刘墨林", "科技信息部", "reports_to"],
        ],
    }

    accepted = _validate_power_map_cleaned_text(
        raw_text=LONG_HAIYOU_RAW * 5,
        cleaned_text=json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")),
        session_id="test",
    )

    assert accepted == ""


def test_cleaning_contract_rejects_compact_department_parent_missing_from_departments():
    cleaned = {
        "g": "建立海油工程组织层级",
        "d": [
            ["科技信息部", "机关部室", "department"],
            ["研发中心", "科技信息部", "department"],
        ],
        "p": [
            ["吕亚平", "研发中心领导", "研发中心"],
        ],
        "e": [],
    }

    accepted = _validate_power_map_cleaned_text(
        raw_text=LONG_HAIYOU_RAW * 5,
        cleaned_text=json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")),
        session_id="test",
    )

    assert accepted == ""


def test_cleaning_contract_rejects_compact_person_department_missing_from_departments():
    cleaned = {
        "g": "建立海油工程组织层级",
        "d": [
            ["海油工程", "", "company"],
            ["科技信息部", "海油工程", "department"],
        ],
        "p": [
            ["吕亚平", "研发中心领导", "研发中心"],
        ],
        "e": [],
    }

    accepted = _validate_power_map_cleaned_text(
        raw_text=LONG_HAIYOU_RAW * 5,
        cleaned_text=json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")),
        session_id="test",
    )

    assert accepted == ""


def test_cleaning_contract_raw_ok_sentinel_keeps_short_instruction_for_planning():
    accepted = _validate_power_map_cleaned_text(
        raw_text="建组织架构：黄宇 CEO，苏女士向黄宇汇报。",
        cleaned_text=_POWER_MAP_CLEAN_RAW_OK,
        session_id="test",
    )

    assert accepted == ""


def test_cleaning_contract_rejects_short_natural_language_summary():
    accepted = _validate_power_map_cleaned_text(
        raw_text=LONG_HAIYOU_RAW,
        cleaned_text="海油工程下设科技信息部和 ITC，你本人向吕亚平汇报。",
        session_id="test",
    )

    assert accepted == ""


def test_cleaning_contract_accepts_fenced_json_but_normalizes_it():
    raw = "背景说明" * 120 + "组织事实：张三向李四汇报。"
    fenced = """```json
{"effective_goal":"建图","people":[{"name":"张三"},{"name":"李四"}],"report_edges":[{"source":"张三","target":"李四"}]}
```"""

    accepted = _validate_power_map_cleaned_text(
        raw_text=raw,
        cleaned_text=fenced,
        session_id="test",
    )

    assert accepted.startswith("{")
    assert "```" not in accepted

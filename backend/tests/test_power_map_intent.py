import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.power_map_service import (  # noqa: E402
    MergeContext,
    PowerNode,
    _parse_power_map_intent,
    _parse_power_map_intent_with_warnings,
    _power_map_intent_to_pseudo_graph,
    _power_map_parallel_edge_warnings,
    _validate_power_map_plan_against_instruction,
    _validate_power_map_intent,
)


def test_parse_power_map_intent_separates_parent_links_and_report_edges():
    plan = {
        "goal": "创建组织架构",
        "departments": [
            {"name": "总裁办", "parent": ""},
            {"name": "财务部", "parent": ""},
        ],
        "people": [
            {"name": "黄宇", "title": "CEO", "parent": "总裁办"},
            {"name": "纪成", "title": "财务总监", "parent": "财务部"},
        ],
        "parent_links": [
            {"child": "纪成", "parent": "财务部", "reason": "所属部门"},
        ],
        "report_edges": [
            {"source": "纪成", "target": "黄宇", "relation": "reports_to"},
        ],
        "layout_roots": ["黄宇"],
        "constraints": ["树状辐射"],
    }

    intent = _parse_power_map_intent(json.dumps(plan, ensure_ascii=False))

    assert intent.goal == "创建组织架构"
    assert [d.name for d in intent.departments] == ["总裁办", "财务部"]
    assert intent.parent_links[0].child == "纪成"
    assert intent.parent_links[0].parent == "财务部"
    assert intent.report_edges[0].source == "纪成"
    assert intent.report_edges[0].target == "黄宇"
    assert intent.report_edges[0].relation == "reports_to"
    assert intent.layout_roots == ["黄宇"]


def test_parse_power_map_intent_accepts_legacy_create_fields():
    plan = {
        "create_departments": [{"name": "销售部", "parent": ""}],
        "create_people": [{"name": "张强", "title": "销售总监", "parent": "销售部"}],
        "report_edges": [],
    }

    intent = _parse_power_map_intent("```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```")

    assert intent.departments[0].name == "销售部"
    assert intent.people[0].name == "张强"
    assert intent.people[0].parent == "销售部"


def test_parse_power_map_intent_repairs_missing_comma_between_fields():
    plan = (
        '{"goal":"build org",'
        '"create_departments":[{"name":"Group","parent":""}],'
        '"create_people":[{"name":"Alice","title":"CIO","parent":"Group"}] '
        '"report_edges":[]}'
    )

    intent, warnings = _parse_power_map_intent_with_warnings(plan)

    assert intent.departments[0].name == "Group"
    assert intent.people[0].name == "Alice"
    assert intent.report_edges == []
    assert warnings and "自动修复" in warnings[0]


def test_parse_power_map_intent_repairs_missing_comma_between_array_objects():
    plan = (
        '{"create_departments":['
        '{"name":"Group","parent":""}'
        '{"name":"IT","parent":"Group"}'
        '],"report_edges":[]}'
    )

    intent, warnings = _parse_power_map_intent_with_warnings(plan)

    assert [(dept.name, dept.parent) for dept in intent.departments] == [
        ("Group", ""),
        ("IT", "Group"),
    ]
    assert warnings


def test_parse_power_map_intent_repairs_unclosed_json_object():
    plan = '{"create_departments":[{"name":"Group","parent":""}],"report_edges":[]'

    intent, warnings = _parse_power_map_intent_with_warnings(plan)

    assert intent.departments[0].name == "Group"
    assert warnings


def test_parse_power_map_intent_extracts_delete_nodes_from_tool_batches():
    plan = {
        "goal": "删除客户成功部及其下属所有人员",
        "tool_batches": [
            {
                "phase": "delete_nodes",
                "calls": [
                    {
                        "tool": "backend_intent",
                        "args": {
                            "action": "delete_department_recursive",
                            "target": "客户成功部",
                            "include_children": True,
                        },
                    }
                ],
                "why": "删除客户成功部容器节点及其所有子节点",
            }
        ],
    }

    intent = _parse_power_map_intent(json.dumps(plan, ensure_ascii=False))

    assert len(intent.delete_nodes) == 1
    assert intent.delete_nodes[0].ref == "客户成功部"
    assert intent.delete_nodes[0].cascade is True


def test_parse_power_map_intent_accepts_compact_cleaning_schema():
    plan = {
        "g": "建立集团组织",
        "d": [
            ["集团", "", "group"],
            ["子公司", "集团", "company"],
            ["研发部", "子公司", "department"],
        ],
        "p": [
            ["张三", "总经理", "子公司"],
            ["李四", "研发负责人", "研发部"],
        ],
        "e": [["李四", "张三", "reports_to"]],
        "c": ["不要混淆子公司和部门"],
    }

    intent = _parse_power_map_intent(json.dumps(plan, ensure_ascii=False))

    assert intent.goal == "建立集团组织"
    assert [(dept.name, dept.parent, dept.kind) for dept in intent.departments] == [
        ("集团", "", "group"),
        ("子公司", "集团", "company"),
        ("研发部", "子公司", "department"),
    ]
    assert [(person.name, person.title, person.parent) for person in intent.people] == [
        ("张三", "总经理", "子公司"),
        ("李四", "研发负责人", "研发部"),
    ]
    assert [(edge.source, edge.target, edge.relation) for edge in intent.report_edges] == [
        ("李四", "张三", "reports_to")
    ]
    assert intent.constraints == ["不要混淆子公司和部门"]


def test_validate_power_map_intent_rejects_missing_parent_and_unknown_edge_endpoint():
    ctx = MergeContext()
    ctx.all_nodes = [PowerNode(id="d1", name="总裁办", node_type="dept")]
    ctx.nodes_by_id = {"d1": ctx.all_nodes[0]}
    ctx.nodes_by_name = {"总裁办": ctx.all_nodes[0]}
    ctx.depts_by_name = {"总裁办": ctx.all_nodes[0]}
    intent = _parse_power_map_intent(
        json.dumps(
            {
                "departments": [{"name": "财务部", "parent": "不存在父级"}],
                "people": [{"name": "纪成", "title": "财务总监", "parent": "财务部"}],
                "report_edges": [{"source": "纪成", "target": "黄宇"}],
            },
            ensure_ascii=False,
        )
    )

    validation = _validate_power_map_intent(intent, ctx)

    assert validation["ok"] is False
    assert any("不存在父级" in err for err in validation["errors"])
    assert any("黄宇" in err for err in validation["errors"])


def test_validate_power_map_intent_rejects_department_hierarchy_reports_to_edges():
    intent = _parse_power_map_intent(
        json.dumps(
            {
                "departments": [
                    {"name": "海油工程", "parent": ""},
                    {"name": "科技信息部", "parent": "海油工程"},
                    {"name": "研发中心", "parent": "科技信息部"},
                    {"name": "ITC", "parent": "研发中心"},
                ],
                "people": [
                    {"name": "吕亚平", "title": "研发中心领导", "parent": "研发中心"},
                ],
                "report_edges": [
                    {"source": "科技信息部", "target": "研发中心", "relation": "reports_to"},
                    {"source": "研发中心", "target": "ITC", "relation": "reports_to"},
                ],
            },
            ensure_ascii=False,
        )
    )

    validation = _validate_power_map_intent(intent, MergeContext())

    assert validation["ok"] is False
    assert any("department hierarchy edge must be parent_link" in err for err in validation["errors"])


def test_plan_validation_rejects_missing_explicit_reporting_edges():
    intent = _parse_power_map_intent(
        json.dumps(
            {
                "departments": [
                    {"name": "数字化管理部", "parent": ""},
                    {"name": "数据部", "parent": "数字化管理部"},
                    {"name": "平台部", "parent": "数字化管理部"},
                ],
                "people": [
                    {"name": "周总", "parent": "数字化管理部"},
                    {"name": "数据负责人", "parent": "数据部"},
                    {"name": "平台负责人", "parent": "平台部"},
                ],
                "report_edges": [],
            },
            ensure_ascii=False,
        )
    )

    errors = _validate_power_map_plan_against_instruction(
        instruction_text="数据负责人、平台负责人都向周总汇报",
        intent=intent,
    )

    assert any("report_edges" in error for error in errors)


def test_power_map_pseudo_graph_splits_hierarchy_parallel_and_reporting_sections():
    intent = _parse_power_map_intent(
        json.dumps(
            {
                "goal": "构建回收宝局部组织关系",
                "create_departments": [
                    {"name": "信息中心", "parent": ""},
                    {"name": "开发组", "parent": "信息中心"},
                    {"name": "运维组", "parent": "信息中心"},
                    {"name": "运营管理部", "parent": ""},
                ],
                "create_people": [
                    {"name": "侯新硕", "title": "CIO", "parent": "信息中心"},
                    {"name": "吴龙", "title": "开发组组长", "parent": "开发组"},
                    {"name": "刘东", "title": "运营管理部部长", "parent": "运营管理部"},
                    {"name": "王忠", "title": "业务人员", "parent": "运营管理部"},
                ],
                "rank_groups": [["信息中心", "运营管理部"]],
                "report_edges": [
                    {
                        "source": "王忠",
                        "target": "刘东",
                        "relation": "reports_to",
                        "reason": "刘东是部长，下面有业务人员王忠",
                    }
                ],
            },
            ensure_ascii=False,
        )
    )

    pseudo = _power_map_intent_to_pseudo_graph(intent)

    assert "部门层级：" in pseudo
    assert "平行关系：" in pseudo
    assert "人员汇报线：" in pseudo
    assert "- 信息中心" in pseudo
    assert "  - 开发组" in pseudo
    assert "- 信息中心 ｜ 运营管理部" in pseudo
    assert "王忠 -> 刘东" in pseudo
    assert "刘东 -> 侯新硕" not in pseudo
    assert "吴龙 -> 侯新硕" not in pseudo


def test_power_map_pseudo_graph_explicitly_shows_no_reporting_edges():
    intent = _parse_power_map_intent(
        json.dumps(
            {
                "create_departments": [
                    {"name": "信息中心", "parent": ""},
                    {"name": "运营管理部", "parent": ""},
                ],
                "rank_groups": [["信息中心", "运营管理部"]],
                "report_edges": [],
            },
            ensure_ascii=False,
        )
    )

    pseudo = _power_map_intent_to_pseudo_graph(intent)

    assert "人员汇报线：" in pseudo
    assert "- 无明确关系线" in pseudo


def test_parallel_edge_warning_is_advisory_only():
    intent = _parse_power_map_intent(
        json.dumps(
            {
                "create_departments": [
                    {"name": "信息中心", "parent": ""},
                    {"name": "开发组", "parent": "信息中心"},
                    {"name": "运营管理部", "parent": ""},
                ],
                "create_people": [
                    {"name": "侯新硕", "title": "CIO", "parent": "信息中心"},
                    {"name": "刘东", "title": "运营管理部部长", "parent": "运营管理部"},
                    {"name": "吴龙", "title": "开发组组长", "parent": "开发组"},
                ],
                "rank_groups": [["信息中心", "运营管理部"]],
                "report_edges": [
                    {"source": "刘东", "target": "侯新硕", "relation": "reports_to"},
                    {"source": "吴龙", "target": "侯新硕", "relation": "reports_to"},
                ],
            },
            ensure_ascii=False,
        )
    )

    warnings = _power_map_parallel_edge_warnings(intent)

    assert warnings == ["请确认跨平行部门汇报是否明确存在：刘东 -> 侯新硕"]

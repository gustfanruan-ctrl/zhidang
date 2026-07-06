import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.power_map_service import (  # noqa: E402
    MergeContext,
    PowerNode,
    _apply_power_map_intent_to_context,
    _parse_power_map_intent,
)


def _apply_plan(plan: dict) -> MergeContext:
    ctx = MergeContext()
    result = _apply_power_map_intent_to_context(
        ctx,
        _parse_power_map_intent(json.dumps(plan, ensure_ascii=False)),
    )
    assert result["ok"] is True, result
    _assert_children_inside_parent_containers(ctx)
    _assert_no_false_department_wrapping(ctx)
    _assert_reports_to_edges_flow_downward(ctx)
    return ctx


def _assert_children_inside_parent_containers(ctx: MergeContext) -> None:
    for node in ctx.all_nodes:
        if not node.parent_dept_id:
            continue
        parent = ctx.nodes_by_id[node.parent_dept_id]
        assert parent.node_type == "dept"
        assert parent.x <= node.x
        assert parent.y <= node.y
        assert node.x + node.w <= parent.x + parent.w
        assert node.y + node.h <= parent.y + parent.h


def _contains_box(outer, inner) -> bool:
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and inner.x + inner.w <= outer.x + outer.w
        and inner.y + inner.h <= outer.y + outer.h
    )


def _is_descendant(ctx: MergeContext, node, ancestor) -> bool:
    seen: set[str] = set()
    parent_id = node.parent_dept_id or ""
    while parent_id and parent_id not in seen:
        if parent_id == ancestor.id:
            return True
        seen.add(parent_id)
        parent = ctx.nodes_by_id.get(parent_id)
        parent_id = parent.parent_dept_id if parent else ""
    return False


def _assert_no_false_department_wrapping(ctx: MergeContext) -> None:
    departments = [node for node in ctx.all_nodes if node.node_type == "dept"]
    for outer in departments:
        for inner in departments:
            if outer.id == inner.id or _is_descendant(ctx, inner, outer):
                continue
            assert not _contains_box(outer, inner), (
                f"{outer.name} visually wraps non-child department {inner.name}"
            )


def _assert_reports_to_edges_flow_downward(ctx: MergeContext) -> None:
    for edge in ctx.edges:
        if str(edge.get("edge_type") or "reports_to") != "reports_to":
            continue
        source = ctx.nodes_by_id[str(edge["source_id"])]
        target = ctx.nodes_by_id[str(edge["target_id"])]
        assert source.y > target.y, f"{source.name} should be below {target.name}"


def _dept_parent(ctx: MergeContext, name: str) -> str:
    node = ctx.nodes_by_name[name]
    if not node.parent_dept_id:
        return ""
    return ctx.nodes_by_id[node.parent_dept_id].name


def _person_parent(ctx: MergeContext, name: str) -> str:
    node = ctx.nodes_by_name[name]
    if not node.parent_dept_id:
        return ""
    return ctx.nodes_by_id[node.parent_dept_id].name


def _reports_to_pairs(ctx: MergeContext) -> set[tuple[str, str]]:
    return {
        (ctx.nodes_by_id[str(edge["source_id"])].name, ctx.nodes_by_id[str(edge["target_id"])].name)
        for edge in ctx.edges
        if str(edge.get("edge_type") or "reports_to") == "reports_to"
    }


HUANGYU_INTENT = {
    "goal": "建一个完整的公司组织架构",
    "departments": [
        {"name": "总裁办", "parent": ""},
        {"name": "财务部", "parent": ""},
        {"name": "销售部", "parent": ""},
        {"name": "华东销售组", "parent": "销售部"},
        {"name": "华南销售组", "parent": "销售部"},
    ],
    "people": [
        {"name": "黄宇", "title": "CEO", "parent": "总裁办"},
        {"name": "苏女士", "title": "总裁助理", "parent": "总裁办"},
        {"name": "纪成", "title": "财务总监", "parent": "财务部"},
        {"name": "王女士", "title": "会计", "parent": "财务部"},
        {"name": "占荣", "title": "会计", "parent": "财务部"},
        {"name": "张强", "title": "销售总监", "parent": "销售部"},
        {"name": "王伟", "title": "组长", "parent": "华东销售组"},
        {"name": "李光昭", "title": "销售经理", "parent": "华东销售组"},
        {"name": "艾翔", "title": "销售经理", "parent": "华东销售组"},
        {"name": "陈大志", "title": "组长", "parent": "华南销售组"},
        {"name": "谭杰桂", "title": "销售经理", "parent": "华南销售组"},
        {"name": "周浩", "title": "销售经理", "parent": "华南销售组"},
    ],
    "report_edges": [
        {"source": "苏女士", "target": "黄宇"},
        {"source": "纪成", "target": "黄宇"},
        {"source": "张强", "target": "黄宇"},
        {"source": "王女士", "target": "纪成"},
        {"source": "占荣", "target": "纪成"},
        {"source": "王伟", "target": "张强"},
        {"source": "陈大志", "target": "张强"},
        {"source": "李光昭", "target": "王伟"},
        {"source": "艾翔", "target": "王伟"},
        {"source": "谭杰桂", "target": "陈大志"},
        {"source": "周浩", "target": "陈大志"},
    ],
}


def test_apply_power_map_intent_creates_departments_people_edges_without_llm_tool_loop():
    ctx = MergeContext()
    intent = _parse_power_map_intent(json.dumps(HUANGYU_INTENT, ensure_ascii=False))

    result = _apply_power_map_intent_to_context(ctx, intent)

    assert result["ok"] is True
    assert result["radial_layout_used"] is True
    assert result["relayout_called"] is False
    assert len(ctx.all_nodes) == len(HUANGYU_INTENT["departments"]) + len(HUANGYU_INTENT["people"])
    assert len(ctx.edges) == len(HUANGYU_INTENT["report_edges"])
    assert ctx.nodes_by_name["黄宇"].y < ctx.nodes_by_name["纪成"].y
    assert ctx.nodes_by_name["总裁办"].y < ctx.nodes_by_name["财务部"].y
    _assert_no_false_department_wrapping(ctx)


def test_existing_graph_local_intent_preserves_existing_node_geometry():
    root = PowerNode(id="root", node_type="dept", name="Fuda", x=120, y=80, w=820, h=420)
    user = PowerNode(
        id="u1",
        node_type="user",
        name="Alice",
        parent_dept_id="root",
        x=180,
        y=180,
        w=160,
        h=72,
    )
    ctx = MergeContext()
    ctx.all_nodes = [root, user]
    ctx.nodes_by_id = {root.id: root, user.id: user}
    ctx.nodes_by_name = {root.name: root, user.name: user}
    ctx.depts_by_name = {root.name: root}
    before = {node.id: (node.x, node.y, node.w, node.h) for node in ctx.all_nodes}
    intent = _parse_power_map_intent(json.dumps({
        "goal": "add one contact under Fuda",
        "people": [{"name": "Bob", "title": "CS", "parent": "Fuda"}],
    }, ensure_ascii=False))

    result = _apply_power_map_intent_to_context(ctx, intent)

    assert result["ok"] is True
    assert result["radial_layout_used"] is False
    assert {node.id: (node.x, node.y, node.w, node.h) for node in [root, user]} == before
    assert ctx.nodes_by_name["Bob"].parent_dept_id == root.id


def test_radial_layout_wraps_wide_root_sibling_departments():
    plan = {
        "goal": "build dreame organization",
        "departments": [
            {"name": "Dreame", "parent": ""},
            {"name": "Factory", "parent": "Dreame"},
            {"name": "China", "parent": "Dreame"},
            {"name": "Incubator1", "parent": "Dreame"},
            {"name": "Incubator2", "parent": "Dreame"},
            {"name": "Incubator3", "parent": "Dreame"},
            {"name": "Incubator4", "parent": "Dreame"},
            {"name": "RobotBU", "parent": "Incubator1"},
            {"name": "WetDryBU", "parent": "Incubator1"},
            {"name": "VacuumBU", "parent": "Incubator1"},
            {"name": "HairDryerBU", "parent": "Incubator1"},
            {"name": "Incubator1IT", "parent": "Incubator1"},
            {"name": "Incubator1Data", "parent": "Incubator1IT"},
            {"name": "Incubator3IT", "parent": "Incubator3"},
            {"name": "Incubator3Data", "parent": "Incubator3IT"},
            {"name": "Incubator4IT", "parent": "Incubator4"},
        ],
        "people": [
            {"name": "ChenLei", "title": "IT owner", "parent": "Incubator1IT"},
            {"name": "CuiShuo", "title": "Data owner", "parent": "Incubator1Data"},
            {"name": "XiaoLi", "title": "FineReport", "parent": "Incubator1Data"},
            {"name": "ZhangBingbing", "title": "", "parent": "Incubator1Data"},
            {"name": "YanShu", "title": "IT owner", "parent": "Incubator3IT"},
            {"name": "HuangZhongrui", "title": "Data owner", "parent": "Incubator3Data"},
            {"name": "ZhangShilei", "title": "IT owner", "parent": "Incubator4IT"},
            {"name": "ZengYuhui", "title": "3/4 IT manager", "parent": "Dreame"},
        ],
        "report_edges": [
            {"source": "CuiShuo", "target": "ChenLei"},
            {"source": "XiaoLi", "target": "CuiShuo"},
            {"source": "ZhangBingbing", "target": "XiaoLi"},
            {"source": "HuangZhongrui", "target": "YanShu"},
            {"source": "YanShu", "target": "ZengYuhui"},
            {"source": "ZhangShilei", "target": "ZengYuhui"},
        ],
    }

    ctx = _apply_plan(plan)

    root = ctx.nodes_by_name["Dreame"]
    assert root.w <= 2700
    assert ctx.nodes_by_name["Incubator1"].y < ctx.nodes_by_name["Incubator3"].y
    assert ("YanShu", "ZengYuhui") in _reports_to_pairs(ctx)
    assert ("ZhangShilei", "ZengYuhui") in _reports_to_pairs(ctx)


def test_apply_power_map_intent_deletes_department_and_children_from_tool_batch():
    ctx = _apply_plan({
        "goal": "seed graph",
        "departments": [
            {"name": "大数据中心", "parent": ""},
            {"name": "客户成功部", "parent": ""},
        ],
        "people": [
            {"name": "吴建峰", "title": "负责人", "parent": "大数据中心"},
            {"name": "客户成功负责人", "title": "部门经理", "parent": "客户成功部"},
            {"name": "客户经理A", "title": "客户经理", "parent": "客户成功部"},
            {"name": "客户经理B", "title": "客户经理", "parent": "客户成功部"},
            {"name": "客户分析师", "title": "数据分析师", "parent": "客户成功部"},
        ],
        "report_edges": [
            {"source": "客户成功负责人", "target": "吴建峰"},
        ],
    })

    delete_plan = {
        "goal": "删除客户成功部门及其下的所有人员",
        "tool_batches": [
            {
                "phase": "delete_nodes",
                "calls": [
                    {
                        "tool": "backend_intent",
                        "args": {
                            "action": "delete_department_recursive",
                            "target": "客户成功部门",
                            "include_children": True,
                        },
                    }
                ],
            }
        ],
    }
    result = _apply_power_map_intent_to_context(
        ctx,
        _parse_power_map_intent(json.dumps(delete_plan, ensure_ascii=False)),
    )

    assert result["ok"] is True
    assert result["deleted"] == 5
    assert "客户成功部" not in ctx.nodes_by_name
    assert "客户成功负责人" not in ctx.nodes_by_name
    assert "客户经理A" not in ctx.nodes_by_name
    assert "客户经理B" not in ctx.nodes_by_name
    assert "客户分析师" not in ctx.nodes_by_name
    assert ctx.edges == []
    assert "大数据中心" in ctx.nodes_by_name
    assert "吴建峰" in ctx.nodes_by_name


def test_apply_power_map_intent_lifts_ceo_office_sibling_departments():
    ctx = MergeContext()
    plan = json.loads(json.dumps(HUANGYU_INTENT, ensure_ascii=False))
    for dept in plan["departments"]:
        if dept["name"] in {"财务部", "销售部"}:
            dept["parent"] = "总裁办"
    intent = _parse_power_map_intent(json.dumps(plan, ensure_ascii=False))

    result = _apply_power_map_intent_to_context(ctx, intent)

    assert result["ok"] is True
    assert ctx.nodes_by_name["总裁办"].parent_dept_id == ""
    assert ctx.nodes_by_name["财务部"].parent_dept_id == ""
    assert ctx.nodes_by_name["销售部"].parent_dept_id == ""
    assert ctx.nodes_by_name["黄宇"].parent_dept_id == ctx.nodes_by_name["总裁办"].id
    assert ctx.nodes_by_name["纪成"].parent_dept_id == ctx.nodes_by_name["财务部"].id
    assert ctx.nodes_by_name["张强"].parent_dept_id == ctx.nodes_by_name["销售部"].id
    assert ctx.nodes_by_name["总裁办"].y < ctx.nodes_by_name["财务部"].y
    assert ctx.nodes_by_name["总裁办"].y < ctx.nodes_by_name["销售部"].y
    _assert_no_false_department_wrapping(ctx)


def test_apply_power_map_intent_preserves_two_level_business_departments():
    plan = {
        "goal": "建立两级销售组织",
        "departments": [
            {"name": "销售部", "parent": ""},
            {"name": "华东销售组", "parent": "销售部"},
            {"name": "华南销售组", "parent": "销售部"},
        ],
        "people": [
            {"name": "张强", "title": "销售总监", "parent": "销售部"},
            {"name": "王伟", "title": "华东组长", "parent": "华东销售组"},
            {"name": "陈大志", "title": "华南组长", "parent": "华南销售组"},
        ],
        "report_edges": [
            {"source": "王伟", "target": "张强"},
            {"source": "陈大志", "target": "张强"},
        ],
    }

    ctx = _apply_plan(plan)

    assert _dept_parent(ctx, "华东销售组") == "销售部"
    assert _dept_parent(ctx, "华南销售组") == "销售部"
    assert _person_parent(ctx, "王伟") == "华东销售组"
    assert _person_parent(ctx, "陈大志") == "华南销售组"


def test_apply_power_map_intent_preserves_three_level_company_department_team():
    plan = {
        "goal": "建立公司到部门到小组的三级组织",
        "departments": [
            {"name": "华东公司", "parent": ""},
            {"name": "客户成功部", "parent": "华东公司"},
            {"name": "KA小组", "parent": "客户成功部"},
            {"name": "续费小组", "parent": "客户成功部"},
        ],
        "people": [
            {"name": "公司总经理", "title": "总经理", "parent": "华东公司"},
            {"name": "客户成功负责人", "title": "部门负责人", "parent": "客户成功部"},
            {"name": "KA组长", "title": "组长", "parent": "KA小组"},
            {"name": "续费组长", "title": "组长", "parent": "续费小组"},
        ],
        "report_edges": [
            {"source": "客户成功负责人", "target": "公司总经理"},
            {"source": "KA组长", "target": "客户成功负责人"},
            {"source": "续费组长", "target": "客户成功负责人"},
        ],
    }

    ctx = _apply_plan(plan)

    assert _dept_parent(ctx, "客户成功部") == "华东公司"
    assert _dept_parent(ctx, "KA小组") == "客户成功部"
    assert _dept_parent(ctx, "续费小组") == "客户成功部"
    assert _person_parent(ctx, "KA组长") == "KA小组"
    assert _person_parent(ctx, "续费组长") == "续费小组"
    assert ("KA组长", "客户成功负责人") in _reports_to_pairs(ctx)


def test_apply_power_map_intent_preserves_four_level_nested_hierarchy():
    plan = {
        "goal": "建立四级研发体系",
        "departments": [
            {"name": "集团", "parent": ""},
            {"name": "数字化中心", "parent": "集团"},
            {"name": "研发部", "parent": "数字化中心"},
            {"name": "平台组", "parent": "研发部"},
        ],
        "people": [
            {"name": "集团总经理", "title": "总经理", "parent": "集团"},
            {"name": "中心负责人", "title": "中心负责人", "parent": "数字化中心"},
            {"name": "研发负责人", "title": "研发负责人", "parent": "研发部"},
            {"name": "平台组长", "title": "组长", "parent": "平台组"},
            {"name": "平台工程师", "title": "工程师", "parent": "平台组"},
        ],
        "report_edges": [
            {"source": "中心负责人", "target": "集团总经理"},
            {"source": "研发负责人", "target": "中心负责人"},
            {"source": "平台组长", "target": "研发负责人"},
            {"source": "平台工程师", "target": "平台组长"},
        ],
    }

    ctx = _apply_plan(plan)

    assert _dept_parent(ctx, "数字化中心") == "集团"
    assert _dept_parent(ctx, "研发部") == "数字化中心"
    assert _dept_parent(ctx, "平台组") == "研发部"
    assert _person_parent(ctx, "平台工程师") == "平台组"
    assert ctx.nodes_by_name["集团"].y < ctx.nodes_by_name["数字化中心"].y
    assert ctx.nodes_by_name["数字化中心"].y < ctx.nodes_by_name["研发部"].y
    assert ctx.nodes_by_name["研发部"].y < ctx.nodes_by_name["平台组"].y


def test_apply_power_map_intent_lifts_ceo_office_roots_without_flattening_nested_teams():
    plan = {
        "goal": "建一个完整公司组织架构：总裁办有 CEO，另下设业务部门和小组",
        "departments": [
            {"name": "总裁办", "parent": ""},
            {"name": "财务部", "parent": "总裁办"},
            {"name": "核算组", "parent": "财务部"},
            {"name": "销售部", "parent": "总裁办"},
            {"name": "华东销售组", "parent": "销售部"},
            {"name": "华南销售组", "parent": "销售部"},
            {"name": "技术部", "parent": "总裁办"},
            {"name": "测试组", "parent": "技术部"},
        ],
        "people": [
            {"name": "黄宇", "title": "CEO", "parent": "总裁办"},
            {"name": "苏女士", "title": "总裁助理", "parent": "总裁办"},
            {"name": "纪成", "title": "财务总监", "parent": "财务部"},
            {"name": "王女士", "title": "会计", "parent": "核算组"},
            {"name": "张强", "title": "销售总监", "parent": "销售部"},
            {"name": "王伟", "title": "华东组长", "parent": "华东销售组"},
            {"name": "陈大志", "title": "华南组长", "parent": "华南销售组"},
            {"name": "王先生", "title": "技术总监", "parent": "技术部"},
            {"name": "程凯", "title": "测试组长", "parent": "测试组"},
        ],
        "report_edges": [
            {"source": "苏女士", "target": "黄宇"},
            {"source": "纪成", "target": "黄宇"},
            {"source": "张强", "target": "黄宇"},
            {"source": "王先生", "target": "黄宇"},
            {"source": "王女士", "target": "纪成"},
            {"source": "王伟", "target": "张强"},
            {"source": "陈大志", "target": "张强"},
            {"source": "程凯", "target": "王先生"},
        ],
    }

    ctx = _apply_plan(plan)

    assert _dept_parent(ctx, "总裁办") == ""
    assert _dept_parent(ctx, "财务部") == ""
    assert _dept_parent(ctx, "销售部") == ""
    assert _dept_parent(ctx, "技术部") == ""
    assert _dept_parent(ctx, "核算组") == "财务部"
    assert _dept_parent(ctx, "华东销售组") == "销售部"
    assert _dept_parent(ctx, "华南销售组") == "销售部"
    assert _dept_parent(ctx, "测试组") == "技术部"
    assert _person_parent(ctx, "苏女士") == "总裁办"
    assert _person_parent(ctx, "王女士") == "核算组"
    assert _person_parent(ctx, "程凯") == "测试组"


def test_apply_power_map_intent_does_not_lift_explicit_office_subteams():
    plan = {
        "goal": "建立总裁办内部组织",
        "departments": [
            {"name": "总裁办", "parent": ""},
            {"name": "秘书处", "parent": "总裁办"},
            {"name": "战略研究组", "parent": "总裁办"},
        ],
        "people": [
            {"name": "黄宇", "title": "CEO", "parent": "总裁办"},
            {"name": "苏女士", "title": "总裁助理", "parent": "秘书处"},
            {"name": "周顾问", "title": "战略顾问", "parent": "战略研究组"},
        ],
        "report_edges": [
            {"source": "苏女士", "target": "黄宇"},
            {"source": "周顾问", "target": "黄宇"},
        ],
        "constraints": ["秘书处和战略研究组明确属于总裁办内部"],
    }

    ctx = _apply_plan(plan)

    assert _dept_parent(ctx, "秘书处") == "总裁办"
    assert _dept_parent(ctx, "战略研究组") == "总裁办"


def test_apply_power_map_intent_preserves_group_subsidiary_business_unit_department_team():
    plan = {
        "goal": "建立集团到一线小组的五级组织",
        "departments": [
            {"name": "星河集团", "parent": ""},
            {"name": "华东子公司", "parent": "星河集团"},
            {"name": "零售事业部", "parent": "华东子公司"},
            {"name": "门店运营部", "parent": "零售事业部"},
            {"name": "上海一区", "parent": "门店运营部"},
        ],
        "people": [
            {"name": "集团总裁", "title": "集团总裁", "parent": "星河集团"},
            {"name": "华东总经理", "title": "子公司总经理", "parent": "华东子公司"},
            {"name": "事业部负责人", "title": "事业部负责人", "parent": "零售事业部"},
            {"name": "运营部长", "title": "部门负责人", "parent": "门店运营部"},
            {"name": "一区主管", "title": "区域主管", "parent": "上海一区"},
        ],
        "report_edges": [
            {"source": "华东总经理", "target": "集团总裁"},
            {"source": "事业部负责人", "target": "华东总经理"},
            {"source": "运营部长", "target": "事业部负责人"},
            {"source": "一区主管", "target": "运营部长"},
        ],
    }

    ctx = _apply_plan(plan)

    assert _dept_parent(ctx, "华东子公司") == "星河集团"
    assert _dept_parent(ctx, "零售事业部") == "华东子公司"
    assert _dept_parent(ctx, "门店运营部") == "零售事业部"
    assert _dept_parent(ctx, "上海一区") == "门店运营部"
    assert _reports_to_pairs(ctx) == {
        ("华东总经理", "集团总裁"),
        ("事业部负责人", "华东总经理"),
        ("运营部长", "事业部负责人"),
        ("一区主管", "运营部长"),
    }


def test_apply_power_map_intent_preserves_hq_departments_and_subsidiaries_under_group():
    plan = {
        "goal": "集团总部部门和两家子公司并列建图",
        "departments": [
            {"name": "集团总部", "parent": ""},
            {"name": "财务中心", "parent": "集团总部"},
            {"name": "信息中心", "parent": "集团总部"},
            {"name": "华南子公司", "parent": "集团总部"},
            {"name": "华北子公司", "parent": "集团总部"},
        ],
        "people": [
            {"name": "董事长", "title": "董事长", "parent": "集团总部"},
            {"name": "财务负责人", "title": "财务中心负责人", "parent": "财务中心"},
            {"name": "CIO", "title": "信息中心负责人", "parent": "信息中心"},
            {"name": "华南总经理", "title": "子公司总经理", "parent": "华南子公司"},
            {"name": "华北总经理", "title": "子公司总经理", "parent": "华北子公司"},
        ],
        "report_edges": [
            {"source": "财务负责人", "target": "董事长"},
            {"source": "CIO", "target": "董事长"},
            {"source": "华南总经理", "target": "董事长"},
            {"source": "华北总经理", "target": "董事长"},
        ],
    }

    ctx = _apply_plan(plan)

    assert _dept_parent(ctx, "财务中心") == "集团总部"
    assert _dept_parent(ctx, "信息中心") == "集团总部"
    assert _dept_parent(ctx, "华南子公司") == "集团总部"
    assert _dept_parent(ctx, "华北子公司") == "集团总部"
    assert ctx.nodes_by_name["集团总部"].y < ctx.nodes_by_name["财务中心"].y
    assert ctx.nodes_by_name["集团总部"].y < ctx.nodes_by_name["华南子公司"].y


def test_apply_power_map_intent_keeps_info_line_edges_separate_from_org_containment():
    plan = {
        "goal": "组织结构和信息化决策链同时建图",
        "departments": [
            {"name": "海油工程", "parent": ""},
            {"name": "科技信息部", "parent": "海油工程"},
            {"name": "研发中心", "parent": "科技信息部"},
            {"name": "ITC", "parent": "研发中心"},
            {"name": "财务部", "parent": "海油工程"},
        ],
        "people": [
            {"name": "分管领导", "title": "分管信息化领导", "parent": "海油工程"},
            {"name": "刘墨林", "title": "科技信息部联系人", "parent": "科技信息部"},
            {"name": "吕亚平", "title": "研发中心领导", "parent": "研发中心"},
            {"name": "你本人", "title": "ITC 技术负责人", "parent": "ITC"},
            {"name": "财务负责人", "title": "财务负责人", "parent": "财务部"},
        ],
        "report_edges": [
            {"source": "刘墨林", "target": "分管领导"},
            {"source": "吕亚平", "target": "刘墨林"},
            {"source": "你本人", "target": "吕亚平"},
            {"source": "财务负责人", "target": "分管领导"},
        ],
        "constraints": ["信息化决策链是汇报/管理关系，不改变部门容器层级"],
    }

    ctx = _apply_plan(plan)

    assert _dept_parent(ctx, "科技信息部") == "海油工程"
    assert _dept_parent(ctx, "研发中心") == "科技信息部"
    assert _dept_parent(ctx, "ITC") == "研发中心"
    assert _dept_parent(ctx, "财务部") == "海油工程"
    assert ("你本人", "吕亚平") in _reports_to_pairs(ctx)
    assert ("财务负责人", "分管领导") in _reports_to_pairs(ctx)


def test_apply_power_map_intent_preserves_region_store_floor_hierarchy():
    plan = {
        "goal": "建立区域到门店到班组的多级零售组织",
        "departments": [
            {"name": "零售公司", "parent": ""},
            {"name": "华南大区", "parent": "零售公司"},
            {"name": "广州城市组", "parent": "华南大区"},
            {"name": "天河门店", "parent": "广州城市组"},
            {"name": "早班班组", "parent": "天河门店"},
        ],
        "people": [
            {"name": "零售总经理", "title": "总经理", "parent": "零售公司"},
            {"name": "大区经理", "title": "大区经理", "parent": "华南大区"},
            {"name": "城市经理", "title": "城市经理", "parent": "广州城市组"},
            {"name": "店长", "title": "店长", "parent": "天河门店"},
            {"name": "班组长", "title": "班组长", "parent": "早班班组"},
        ],
        "report_edges": [
            {"source": "大区经理", "target": "零售总经理"},
            {"source": "城市经理", "target": "大区经理"},
            {"source": "店长", "target": "城市经理"},
            {"source": "班组长", "target": "店长"},
        ],
    }

    ctx = _apply_plan(plan)

    assert _dept_parent(ctx, "华南大区") == "零售公司"
    assert _dept_parent(ctx, "广州城市组") == "华南大区"
    assert _dept_parent(ctx, "天河门店") == "广州城市组"
    assert _dept_parent(ctx, "早班班组") == "天河门店"


def test_apply_radial_org_layout_avoids_repeated_fit_for_people_heavy_department():
    ctx = MergeContext()
    plan = {
        "departments": [{"name": "客服部", "parent": ""}],
        "people": [{"name": f"客服{i}", "parent": "客服部"} for i in range(9)],
        "report_edges": [],
    }
    intent = _parse_power_map_intent(json.dumps(plan, ensure_ascii=False))

    result = _apply_power_map_intent_to_context(ctx, intent)
    dept = ctx.nodes_by_name["客服部"]
    people = [n for n in ctx.all_nodes if n.node_type == "user"]

    assert result["ok"] is True
    assert result["estimated_dept_sizes"]["客服部"]["w"] == dept.w
    assert all(dept.x <= p.x and p.x + p.w <= dept.x + dept.w for p in people)
    assert all(dept.y <= p.y and p.y + p.h <= dept.y + dept.h for p in people)

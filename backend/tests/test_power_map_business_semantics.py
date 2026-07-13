import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.power_map_service import (  # noqa: E402
    MergeContext,
    _apply_power_map_intent_to_context,
    _parse_power_map_intent,
)


def _apply_case(case: dict) -> MergeContext:
    ctx = MergeContext()
    result = _apply_power_map_intent_to_context(
        ctx,
        _parse_power_map_intent(json.dumps(case["plan"], ensure_ascii=False)),
    )
    assert result["ok"] is True, result
    _assert_containment(ctx)
    _assert_sibling_non_overlap(ctx)
    _assert_no_false_department_wrapping(ctx)
    _assert_reports_downward(ctx)
    return ctx


def _assert_containment(ctx: MergeContext) -> None:
    for node in ctx.all_nodes:
        if not node.parent_dept_id:
            continue
        parent = ctx.nodes_by_id[node.parent_dept_id]
        assert parent.x <= node.x, node.name
        assert parent.y <= node.y, node.name
        assert node.x + node.w <= parent.x + parent.w, node.name
        assert node.y + node.h <= parent.y + parent.h, node.name


def _overlap(a, b) -> bool:
    return not (
        a.x + a.w <= b.x
        or b.x + b.w <= a.x
        or a.y + a.h <= b.y
        or b.y + b.h <= a.y
    )


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


def _assert_sibling_non_overlap(ctx: MergeContext) -> None:
    by_parent: dict[str, list] = {}
    for node in ctx.all_nodes:
        by_parent.setdefault(node.parent_dept_id or "", []).append(node)
    for siblings in by_parent.values():
        for index, left in enumerate(siblings):
            for right in siblings[index + 1 :]:
                assert not _overlap(left, right), f"{left.name} overlaps {right.name}"


def _assert_reports_downward(ctx: MergeContext) -> None:
    for edge in ctx.edges:
        if str(edge.get("edge_type") or "reports_to") != "reports_to":
            continue
        source = ctx.nodes_by_id[str(edge["source_id"])]
        target = ctx.nodes_by_id[str(edge["target_id"])]
        assert source.y > target.y, f"{source.name} should be below {target.name}"


def _dept_parent(ctx: MergeContext, name: str) -> str:
    node = ctx.nodes_by_name[name]
    return ctx.nodes_by_id[node.parent_dept_id].name if node.parent_dept_id else ""


def _person_parent(ctx: MergeContext, name: str) -> str:
    node = ctx.nodes_by_name[name]
    return ctx.nodes_by_id[node.parent_dept_id].name if node.parent_dept_id else ""


def _edge_pairs(ctx: MergeContext, edge_type: str = "reports_to") -> set[tuple[str, str]]:
    return {
        (ctx.nodes_by_id[str(edge["source_id"])].name, ctx.nodes_by_id[str(edge["target_id"])].name)
        for edge in ctx.edges
        if str(edge.get("edge_type") or "reports_to") == edge_type
    }


BUSINESS_SEMANTIC_CASES = [
    {
        "name": "holding_group_to_subsidiary_business_unit_department_team",
        "plan": {
            "goal": "控股集团到一线班组五级建图",
            "departments": [
                {"name": "控股集团", "parent": ""},
                {"name": "制造子公司", "parent": "控股集团"},
                {"name": "智能制造事业部", "parent": "制造子公司"},
                {"name": "生产管理部", "parent": "智能制造事业部"},
                {"name": "A线班组", "parent": "生产管理部"},
            ],
            "people": [
                {"name": "集团董事长", "title": "董事长", "parent": "控股集团"},
                {"name": "子公司总经理", "title": "总经理", "parent": "制造子公司"},
                {"name": "事业部总监", "title": "事业部总监", "parent": "智能制造事业部"},
                {"name": "生产部长", "title": "部长", "parent": "生产管理部"},
                {"name": "班组长", "title": "班组长", "parent": "A线班组"},
            ],
            "report_edges": [
                {"source": "子公司总经理", "target": "集团董事长"},
                {"source": "事业部总监", "target": "子公司总经理"},
                {"source": "生产部长", "target": "事业部总监"},
                {"source": "班组长", "target": "生产部长"},
            ],
        },
        "dept_parents": {
            "制造子公司": "控股集团",
            "智能制造事业部": "制造子公司",
            "生产管理部": "智能制造事业部",
            "A线班组": "生产管理部",
        },
    },
    {
        "name": "headquarters_functions_and_subsidiaries_are_peers",
        "plan": {
            "goal": "总部职能部门和子公司并列",
            "departments": [
                {"name": "集团总部", "parent": ""},
                {"name": "财务中心", "parent": "集团总部"},
                {"name": "信息中心", "parent": "集团总部"},
                {"name": "华东子公司", "parent": "集团总部"},
                {"name": "华南子公司", "parent": "集团总部"},
            ],
            "people": [
                {"name": "集团总裁", "title": "总裁", "parent": "集团总部"},
                {"name": "财务负责人", "title": "财务负责人", "parent": "财务中心"},
                {"name": "CIO", "title": "CIO", "parent": "信息中心"},
                {"name": "华东总经理", "title": "总经理", "parent": "华东子公司"},
                {"name": "华南总经理", "title": "总经理", "parent": "华南子公司"},
            ],
            "report_edges": [
                {"source": "财务负责人", "target": "集团总裁"},
                {"source": "CIO", "target": "集团总裁"},
                {"source": "华东总经理", "target": "集团总裁"},
                {"source": "华南总经理", "target": "集团总裁"},
            ],
        },
        "dept_parents": {
            "财务中心": "集团总部",
            "信息中心": "集团总部",
            "华东子公司": "集团总部",
            "华南子公司": "集团总部",
        },
    },
    {
        "name": "matrix_project_line_keeps_org_containment",
        "plan": {
            "goal": "矩阵项目关系不改变组织归属",
            "departments": [
                {"name": "工程公司", "parent": ""},
                {"name": "设计院", "parent": "工程公司"},
                {"name": "采购中心", "parent": "工程公司"},
                {"name": "建造基地", "parent": "工程公司"},
                {"name": "海上项目组", "parent": "工程公司"},
            ],
            "people": [
                {"name": "项目经理", "title": "项目经理", "parent": "海上项目组"},
                {"name": "设计负责人", "title": "设计负责人", "parent": "设计院"},
                {"name": "采购负责人", "title": "采购负责人", "parent": "采购中心"},
                {"name": "建造负责人", "title": "建造负责人", "parent": "建造基地"},
            ],
            "report_edges": [
                {"source": "设计负责人", "target": "项目经理", "relation": "influences"},
                {"source": "采购负责人", "target": "项目经理", "relation": "influences"},
                {"source": "建造负责人", "target": "项目经理", "relation": "influences"},
            ],
            "constraints": ["项目矩阵是协作关系，不改变设计院、采购中心、建造基地的组织归属"],
        },
        "dept_parents": {
            "设计院": "工程公司",
            "采购中心": "工程公司",
            "建造基地": "工程公司",
            "海上项目组": "工程公司",
        },
        "influences": {
            ("设计负责人", "项目经理"),
            ("采购负责人", "项目经理"),
            ("建造负责人", "项目经理"),
        },
    },
    {
        "name": "regional_retail_store_shift_hierarchy",
        "plan": {
            "goal": "零售区域门店班组层级",
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
        },
        "dept_parents": {
            "华南大区": "零售公司",
            "广州城市组": "华南大区",
            "天河门店": "广州城市组",
            "早班班组": "天河门店",
        },
    },
    {
        "name": "ceo_office_wrongly_wrapping_business_departments_is_lifted",
        "plan": {
            "goal": "建一个完整公司组织架构",
            "departments": [
                {"name": "总裁办", "parent": ""},
                {"name": "财务部", "parent": "总裁办"},
                {"name": "销售部", "parent": "总裁办"},
                {"name": "技术部", "parent": "总裁办"},
                {"name": "测试组", "parent": "技术部"},
            ],
            "people": [
                {"name": "黄宇", "title": "CEO", "parent": "总裁办"},
                {"name": "苏女士", "title": "总裁助理", "parent": "总裁办"},
                {"name": "纪成", "title": "财务总监", "parent": "财务部"},
                {"name": "张强", "title": "销售总监", "parent": "销售部"},
                {"name": "王先生", "title": "技术总监", "parent": "技术部"},
                {"name": "程凯", "title": "测试组长", "parent": "测试组"},
            ],
            "report_edges": [
                {"source": "苏女士", "target": "黄宇"},
                {"source": "纪成", "target": "黄宇"},
                {"source": "张强", "target": "黄宇"},
                {"source": "王先生", "target": "黄宇"},
                {"source": "程凯", "target": "王先生"},
            ],
        },
        "dept_parents": {
            "总裁办": "",
            "财务部": "",
            "销售部": "",
            "技术部": "",
            "测试组": "技术部",
        },
        "person_parents": {
            "黄宇": "总裁办",
            "纪成": "财务部",
            "张强": "销售部",
            "程凯": "测试组",
        },
    },
]


@pytest.mark.parametrize("case", BUSINESS_SEMANTIC_CASES, ids=[case["name"] for case in BUSINESS_SEMANTIC_CASES])
def test_power_map_business_semantic_golden_cases(case):
    ctx = _apply_case(case)

    for child, parent in case.get("dept_parents", {}).items():
        assert _dept_parent(ctx, child) == parent
    for child, parent in case.get("person_parents", {}).items():
        assert _person_parent(ctx, child) == parent
    if case.get("influences"):
        assert case["influences"].issubset(_edge_pairs(ctx, "influences"))


def test_reporting_departments_are_lifted_without_explicit_containment():
    case = {
        "plan": {
            "goal": "各平行部门负责人向数字化负责人汇报",
            "departments": [
                {"name": "数字化管理部", "parent": ""},
                {"name": "数据部", "parent": "数字化管理部"},
                {"name": "平台部", "parent": "数字化管理部"},
                {"name": "产品部", "parent": "数字化管理部"},
            ],
            "people": [
                {"name": "周总", "title": "数字化负责人", "parent": "数字化管理部"},
                {"name": "数据负责人", "title": "负责人", "parent": "数据部"},
                {"name": "平台负责人", "title": "负责人", "parent": "平台部"},
                {"name": "产品负责人", "title": "负责人", "parent": "产品部"},
            ],
            "report_edges": [
                {"source": "数据负责人", "target": "周总"},
                {"source": "平台负责人", "target": "周总"},
                {"source": "产品负责人", "target": "周总"},
            ],
        }
    }

    ctx = _apply_case(case)

    assert _dept_parent(ctx, "数字化管理部") == ""
    assert _dept_parent(ctx, "数据部") == ""
    assert _dept_parent(ctx, "平台部") == ""
    assert _dept_parent(ctx, "产品部") == ""
    assert {
        ("数据负责人", "周总"),
        ("平台负责人", "周总"),
        ("产品负责人", "周总"),
    }.issubset(_edge_pairs(ctx))


def test_explicit_department_containment_survives_reporting_edges():
    case = {
        "plan": {
            "goal": "数字化管理部下设数据部、平台部、产品部，各部门负责人向周总汇报",
            "departments": [
                {"name": "数字化管理部", "parent": ""},
                {"name": "数据部", "parent": "数字化管理部", "notes": "数字化管理部下设数据部"},
                {"name": "平台部", "parent": "数字化管理部", "notes": "数字化管理部下设平台部"},
                {"name": "产品部", "parent": "数字化管理部", "notes": "数字化管理部下设产品部"},
            ],
            "people": [
                {"name": "周总", "title": "数字化负责人", "parent": "数字化管理部"},
                {"name": "数据负责人", "parent": "数据部"},
                {"name": "平台负责人", "parent": "平台部"},
                {"name": "产品负责人", "parent": "产品部"},
            ],
            "report_edges": [
                {"source": "数据负责人", "target": "周总"},
                {"source": "平台负责人", "target": "周总"},
                {"source": "产品负责人", "target": "周总"},
            ],
        }
    }

    ctx = _apply_case(case)

    assert _dept_parent(ctx, "数据部") == "数字化管理部"
    assert _dept_parent(ctx, "平台部") == "数字化管理部"
    assert _dept_parent(ctx, "产品部") == "数字化管理部"

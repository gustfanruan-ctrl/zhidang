import asyncio
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
from tests.power_map_model_benchmark import (  # noqa: E402
    BENCHMARK_CASE_GROUPS,
    BENCHMARK_INTENTS,
    RunStat,
    _benchmark_output_filename,
    _build_benchmark_summary,
    _run_intent_case,
    _resolve_case_names,
    _validate_case_result,
)


def _layout_snapshot(ctx: MergeContext) -> dict:
    return {
        "nodes": [
            {
                "id": n.id,
                "name": n.name,
                "type": "person" if n.node_type == "user" else "department",
                "parent_dept_id": n.parent_dept_id,
                "pid": n.pid,
                "position": n.position,
                "x": float(n.x),
                "y": float(n.y),
                "w": float(n.w),
                "h": float(n.h),
            }
            for n in ctx.all_nodes
        ],
        "edges": [
            {
                "id": str(e.get("id", "")),
                "source_id": str(e.get("source_id", "")),
                "target_id": str(e.get("target_id", "")),
                "edge_type": str(e.get("edge_type", "")),
            }
            for e in ctx.edges
        ],
    }


def _stat_from_plan(plan: dict) -> tuple[dict, RunStat]:
    ctx = MergeContext()
    intent = _parse_power_map_intent(json.dumps(plan, ensure_ascii=False))
    result = _apply_power_map_intent_to_context(ctx, intent)
    stat = RunStat(
        model="kimi-k2.6",
        ok=True,
        events=[{"type": "graph_state", "data": {"layout_snapshot": _layout_snapshot(ctx)}}],
    )
    return result, stat


def test_model_benchmark_case_resolver_supports_lists_all_and_deduping():
    selected = _resolve_case_names(
        "huangyu_org",
        "three_level_company_team,four_level_region_store,three_level_company_team",
    )

    assert selected == ["three_level_company_team", "four_level_region_store"]
    assert "huangyu_org" in _resolve_case_names("ignored", "all")
    with pytest.raises(ValueError, match="unknown benchmark case"):
        _resolve_case_names("huangyu_org", "missing_case")


def test_model_benchmark_case_resolver_supports_named_groups():
    assert _resolve_case_names("huangyu_org", "semantic_smoke") == BENCHMARK_CASE_GROUPS["semantic_smoke"]
    assert _resolve_case_names("huangyu_org", "semantic_smoke,hq_subsidiary") == [
        *BENCHMARK_CASE_GROUPS["semantic_smoke"],
        "hq_subsidiary",
    ]
    assert _resolve_case_names("huangyu_org", "semantic_smoke,huangyu_org") == BENCHMARK_CASE_GROUPS["semantic_smoke"]


def test_model_benchmark_output_filename_prevents_multi_case_overwrite():
    assert _benchmark_output_filename("huangyu_org", "kimi-k2.6", multi_case=False) == "kimi-k2.6.json"
    assert (
        _benchmark_output_filename("four_level_region_store", "kimi/k2.6", multi_case=True)
        == "four_level_region_store__kimi_k2.6.json"
    )


def test_model_benchmark_summary_marks_failures_and_counts_runs():
    passed = RunStat(model="kimi-k2.6", case="huangyu_org", ok=True, validation={"ok": True, "errors": []})
    failed = RunStat(
        model="kimi-k2.6",
        case="four_level_region_store",
        ok=False,
        error="validation_failed: dept_parent 广州城市组",
        validation={"ok": False, "errors": ["dept_parent 广州城市组: '' != '华南大区'"]},
    )

    summary = _build_benchmark_summary(
        stats=[passed, failed],
        run_cases=["huangyu_org", "four_level_region_store"],
        version_id="test-version",
        no_commit=True,
        dry_run_intent=False,
    )

    assert summary["ok"] is False
    assert summary["run_count"] == 2
    assert summary["pass_count"] == 1
    assert summary["fail_count"] == 1
    assert summary["failed"] == [
        {
            "case": "four_level_region_store",
            "model": "kimi-k2.6",
            "error": "validation_failed: dept_parent 广州城市组",
            "validation": {"ok": False, "errors": ["dept_parent 广州城市组: '' != '华南大区'"]},
        }
    ]


def test_model_benchmark_intent_dry_run_cases_self_validate():
    failures = []
    for case_name in sorted(BENCHMARK_INTENTS):
        stat = asyncio.run(_run_intent_case(case_name, "intent-dry-run", "test-version"))
        if stat.ok:
            stat.validation = _validate_case_result(case_name, stat)
            if not stat.validation.get("ok"):
                failures.append((case_name, stat.validation.get("errors", [])))
        else:
            failures.append((case_name, [stat.error]))

    assert failures == []


def test_huangyu_org_chart_benchmark_converges_without_relayout():
    ctx = MergeContext()
    intent = _parse_power_map_intent(
        json.dumps(
            {
                "departments": [
                    {"name": "总裁办", "parent": ""},
                    {"name": "财务部", "parent": ""},
                    {"name": "销售部", "parent": ""},
                ],
                "people": [
                    {"name": "黄宇", "title": "CEO", "parent": "总裁办"},
                    {"name": "纪成", "title": "财务总监", "parent": "财务部"},
                    {"name": "张强", "title": "销售总监", "parent": "销售部"},
                ],
                "report_edges": [
                    {"source": "纪成", "target": "黄宇"},
                    {"source": "张强", "target": "黄宇"},
                ],
            },
            ensure_ascii=False,
        )
    )

    result = _apply_power_map_intent_to_context(ctx, intent)

    assert result["ok"] is True
    assert result["relayout_called"] is False
    assert result["radial_layout_used"] is True
    assert result["nodes"] == 6
    assert result["edges"] == 2


def test_large_parallel_org_has_bounded_aspect_ratio():
    departments = [{"name": "领导办公室", "parent": ""}]
    people = [{"name": "周总", "title": "负责人", "parent": "领导办公室"}]
    report_edges = []
    for index in range(30):
        department = f"业务部门{index:02d}"
        leader = f"负责人{index:02d}"
        departments.append({"name": department, "parent": "领导办公室"})
        people.append({"name": leader, "title": "部门负责人", "parent": department})
        report_edges.append({"source": leader, "target": "周总"})

    ctx = MergeContext()
    result = _apply_power_map_intent_to_context(
        ctx,
        _parse_power_map_intent(
            json.dumps(
                {
                    "goal": "30 个平行部门负责人向周总汇报",
                    "departments": departments,
                    "people": people,
                    "report_edges": report_edges,
                },
                ensure_ascii=False,
            )
        ),
    )

    assert result["ok"] is True
    min_x = min(node.x for node in ctx.all_nodes)
    min_y = min(node.y for node in ctx.all_nodes)
    max_x = max(node.x + node.w for node in ctx.all_nodes)
    max_y = max(node.y + node.h for node in ctx.all_nodes)
    assert (max_x - min_x) / (max_y - min_y) < 8


def test_huangyu_validator_accepts_neutral_company_root_for_top_level_siblings():
    result, stat = _stat_from_plan(
        {
            "departments": [
                {"name": "公司总部", "parent": ""},
                {"name": "总裁办", "parent": "公司总部"},
                {"name": "财务部", "parent": "公司总部"},
                {"name": "销售部", "parent": "公司总部"},
                {"name": "华东销售组", "parent": "销售部"},
                {"name": "华南销售组", "parent": "销售部"},
                {"name": "市场部", "parent": "公司总部"},
                {"name": "技术部", "parent": "公司总部"},
                {"name": "测试组", "parent": "技术部"},
                {"name": "人力资源部", "parent": "公司总部"},
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
                {"name": "吴博昂", "title": "市场总监", "parent": "市场部"},
                {"name": "谢博", "title": "市场专员", "parent": "市场部"},
                {"name": "朱先生", "title": "市场专员", "parent": "市场部"},
                {"name": "王先生", "title": "技术总监", "parent": "技术部"},
                {"name": "程凯", "title": "测试组长", "parent": "测试组"},
                {"name": "虚拟测试人员", "title": "测试工程师", "parent": "测试组"},
                {"name": "测试", "title": "测试工程师", "parent": "测试组"},
                {"name": "测试2", "title": "测试工程师", "parent": "测试组"},
                {"name": "黄先生", "title": "HR 总监", "parent": "人力资源部"},
                {"name": "曹强", "title": "HR 专员", "parent": "人力资源部"},
                {"name": "陆冠顺", "title": "HR 专员", "parent": "人力资源部"},
            ],
            "report_edges": [
                {"source": "苏女士", "target": "黄宇"},
                {"source": "纪成", "target": "黄宇"},
                {"source": "王女士", "target": "纪成"},
                {"source": "占荣", "target": "纪成"},
                {"source": "张强", "target": "黄宇"},
                {"source": "王伟", "target": "张强"},
                {"source": "李光昭", "target": "王伟"},
                {"source": "艾翔", "target": "王伟"},
                {"source": "陈大志", "target": "张强"},
                {"source": "谭杰桂", "target": "陈大志"},
                {"source": "周浩", "target": "陈大志"},
                {"source": "吴博昂", "target": "黄宇"},
                {"source": "谢博", "target": "吴博昂"},
                {"source": "朱先生", "target": "吴博昂"},
                {"source": "王先生", "target": "黄宇"},
                {"source": "程凯", "target": "王先生"},
                {"source": "虚拟测试人员", "target": "程凯"},
                {"source": "测试", "target": "程凯"},
                {"source": "测试2", "target": "程凯"},
                {"source": "黄先生", "target": "黄宇"},
                {"source": "曹强", "target": "黄先生"},
                {"source": "陆冠顺", "target": "黄先生"},
            ],
        }
    )

    validation = _validate_case_result("huangyu_org", stat)

    assert result["ok"] is True
    assert validation["ok"] is True


def test_haiyou_long_prompt_benchmark_uses_clean_intent_and_radial_layout():
    ctx = MergeContext()
    intent = _parse_power_map_intent(
        json.dumps(
            {
                "goal": "海油工程组织和信息化条线建图",
                "departments": [
                    {"name": "中国海洋石油集团", "parent": ""},
                    {"name": "海洋石油工程股份有限公司", "parent": "中国海洋石油集团"},
                    {"name": "机关部室", "parent": "海洋石油工程股份有限公司"},
                    {"name": "科技信息部", "parent": "机关部室"},
                    {"name": "研发中心", "parent": "科技信息部"},
                    {"name": "ITC", "parent": "研发中心"},
                ],
                "people": [
                    {"name": "吕亚平", "title": "研发中心领导", "parent": "研发中心"},
                    {"name": "你本人", "title": "ITC 副职/技术负责人", "parent": "ITC"},
                    {"name": "刘墨林", "title": "科技信息部联系人", "parent": "科技信息部"},
                ],
                "report_edges": [
                    {"source": "你本人", "target": "吕亚平"},
                    {"source": "刘墨林", "target": "科技信息部"},
                ],
            },
            ensure_ascii=False,
        )
    )

    result = _apply_power_map_intent_to_context(ctx, intent)

    assert result["ok"] is True
    assert result["radial_layout_used"] is True
    assert result["fallback_reason"] == ""
    assert result["nodes"] == 9


def test_model_benchmark_validator_checks_business_semantics():
    result, stat = _stat_from_plan(
        {
            "departments": [
                {"name": "集团总部", "parent": ""},
                {"name": "财务中心", "parent": "集团总部"},
                {"name": "信息中心", "parent": "集团总部"},
                {"name": "华东子公司", "parent": "集团总部"},
                {"name": "华南子公司", "parent": "集团总部"},
            ],
            "people": [
                {"name": "集团总裁", "title": "总裁", "parent": "集团总部"},
                {"name": "财务负责人", "parent": "财务中心"},
                {"name": "CIO", "parent": "信息中心"},
                {"name": "华东总经理", "parent": "华东子公司"},
                {"name": "华南总经理", "parent": "华南子公司"},
            ],
            "report_edges": [
                {"source": "财务负责人", "target": "集团总裁"},
                {"source": "CIO", "target": "集团总裁"},
                {"source": "华东总经理", "target": "集团总裁"},
                {"source": "华南总经理", "target": "集团总裁"},
            ],
        }
    )

    validation = _validate_case_result("hq_subsidiary", stat)

    assert result["ok"] is True
    assert validation["ok"] is True


@pytest.mark.parametrize(
    ("case_name", "plan"),
    [
        (
            "three_level_company_team",
            {
                "departments": [
                    {"name": "华东公司", "parent": ""},
                    {"name": "客户成功部", "parent": "华东公司"},
                    {"name": "KA小组", "parent": "客户成功部"},
                    {"name": "续费小组", "parent": "客户成功部"},
                ],
                "people": [
                    {"name": "公司总经理", "parent": "华东公司"},
                    {"name": "客户成功负责人", "parent": "客户成功部"},
                    {"name": "KA组长", "parent": "KA小组"},
                    {"name": "续费组长", "parent": "续费小组"},
                ],
                "report_edges": [
                    {"source": "客户成功负责人", "target": "公司总经理"},
                    {"source": "KA组长", "target": "客户成功负责人"},
                    {"source": "续费组长", "target": "客户成功负责人"},
                ],
            },
        ),
        (
            "four_level_region_store",
            {
                "departments": [
                    {"name": "零售公司", "parent": ""},
                    {"name": "华南大区", "parent": "零售公司"},
                    {"name": "广州城市组", "parent": "华南大区"},
                    {"name": "天河门店", "parent": "广州城市组"},
                    {"name": "早班班组", "parent": "天河门店"},
                ],
                "people": [
                    {"name": "零售总经理", "parent": "零售公司"},
                    {"name": "大区经理", "parent": "华南大区"},
                    {"name": "城市经理", "parent": "广州城市组"},
                    {"name": "店长", "parent": "天河门店"},
                    {"name": "班组长", "parent": "早班班组"},
                ],
                "report_edges": [
                    {"source": "大区经理", "target": "零售总经理"},
                    {"source": "城市经理", "target": "大区经理"},
                    {"source": "店长", "target": "城市经理"},
                    {"source": "班组长", "target": "店长"},
                ],
            },
        ),
    ],
)
def test_model_benchmark_validator_checks_multilevel_business_cases(case_name, plan):
    result, stat = _stat_from_plan(plan)

    validation = _validate_case_result(case_name, stat)

    assert result["ok"] is True
    assert validation["ok"] is True


def test_model_benchmark_validator_rejects_ceo_office_visual_wrapping():
    stat = RunStat(model="kimi-k2.6", case="huangyu_org", ok=True)
    stat.events.append(
        {
            "type": "graph_state",
            "data": {
                "layout_snapshot": {
                    "nodes": [
                        {
                            "id": "d-office",
                            "name": "总裁办",
                            "type": "department",
                            "parent_dept_id": "",
                            "x": 0,
                            "y": 0,
                            "w": 1000,
                            "h": 500,
                        },
                        {
                            "id": "d-finance",
                            "name": "财务部",
                            "type": "department",
                            "parent_dept_id": "",
                            "x": 100,
                            "y": 180,
                            "w": 220,
                            "h": 160,
                        },
                        {
                            "id": "d-sales",
                            "name": "销售部",
                            "type": "department",
                            "parent_dept_id": "",
                            "x": 380,
                            "y": 180,
                            "w": 260,
                            "h": 160,
                        },
                        {
                            "id": "p-ceo",
                            "name": "黄宇",
                            "type": "person",
                            "parent_dept_id": "d-office",
                            "x": 420,
                            "y": 60,
                            "w": 120,
                            "h": 60,
                        },
                        {
                            "id": "p-finance",
                            "name": "纪成",
                            "type": "person",
                            "parent_dept_id": "d-finance",
                            "x": 150,
                            "y": 220,
                            "w": 120,
                            "h": 60,
                        },
                        {
                            "id": "p-sales",
                            "name": "张强",
                            "type": "person",
                            "parent_dept_id": "d-sales",
                            "x": 450,
                            "y": 220,
                            "w": 120,
                            "h": 60,
                        },
                    ],
                    "edges": [
                        {
                            "id": "e-finance",
                            "source_id": "p-finance",
                            "target_id": "p-ceo",
                            "edge_type": "reports_to",
                        },
                        {
                            "id": "e-sales",
                            "source_id": "p-sales",
                            "target_id": "p-ceo",
                            "edge_type": "reports_to",
                        },
                    ],
                }
            },
        }
    )

    validation = _validate_case_result("huangyu_org", stat)

    assert validation["ok"] is False
    assert any("false dept containment 总裁办 wraps non-child 财务部" in err for err in validation["errors"])


@pytest.mark.parametrize(
    ("case_name", "plan", "expected_error_fragment"),
    [
        (
            "four_level_region_store",
            {
                "departments": [
                    {"name": "零售公司", "parent": ""},
                    {"name": "华南大区", "parent": "零售公司"},
                    {"name": "广州城市组", "parent": ""},
                    {"name": "天河门店", "parent": ""},
                    {"name": "早班班组", "parent": ""},
                ],
                "people": [
                    {"name": "零售总经理", "parent": "零售公司"},
                    {"name": "大区经理", "parent": "华南大区"},
                    {"name": "城市经理", "parent": "广州城市组"},
                    {"name": "店长", "parent": "天河门店"},
                    {"name": "班组长", "parent": "早班班组"},
                ],
                "report_edges": [
                    {"source": "大区经理", "target": "零售总经理"},
                    {"source": "城市经理", "target": "大区经理"},
                    {"source": "店长", "target": "城市经理"},
                    {"source": "班组长", "target": "店长"},
                ],
            },
            "dept_parent 广州城市组",
        ),
        (
            "hq_subsidiary",
            {
                "departments": [
                    {"name": "集团总部", "parent": ""},
                    {"name": "财务中心", "parent": "集团总部"},
                    {"name": "信息中心", "parent": "集团总部"},
                    {"name": "华东子公司", "parent": "信息中心"},
                    {"name": "华南子公司", "parent": "信息中心"},
                ],
                "people": [
                    {"name": "集团总裁", "parent": "集团总部"},
                    {"name": "财务负责人", "parent": "财务中心"},
                    {"name": "CIO", "parent": "信息中心"},
                    {"name": "华东总经理", "parent": "华东子公司"},
                    {"name": "华南总经理", "parent": "华南子公司"},
                ],
                "report_edges": [
                    {"source": "财务负责人", "target": "集团总裁"},
                    {"source": "CIO", "target": "集团总裁"},
                    {"source": "华东总经理", "target": "集团总裁"},
                    {"source": "华南总经理", "target": "集团总裁"},
                ],
            },
            "dept_parent 华东子公司",
        ),
        (
            "three_level_company_team",
            {
                "departments": [
                    {"name": "华东公司", "parent": ""},
                    {"name": "客户成功部", "parent": "华东公司"},
                    {"name": "KA小组", "parent": "华东公司"},
                    {"name": "续费小组", "parent": "华东公司"},
                ],
                "people": [
                    {"name": "公司总经理", "parent": "华东公司"},
                    {"name": "客户成功负责人", "parent": "客户成功部"},
                    {"name": "KA组长", "parent": "KA小组"},
                    {"name": "续费组长", "parent": "续费小组"},
                ],
                "report_edges": [
                    {"source": "客户成功负责人", "target": "公司总经理"},
                    {"source": "KA组长", "target": "客户成功负责人"},
                    {"source": "续费组长", "target": "客户成功负责人"},
                ],
            },
            "dept_parent KA小组",
        ),
    ],
)
def test_model_benchmark_validator_rejects_flattened_or_misnested_business_cases(
    case_name,
    plan,
    expected_error_fragment,
):
    result, stat = _stat_from_plan(plan)

    validation = _validate_case_result(case_name, stat)

    assert result["ok"] is True
    assert validation["ok"] is False
    assert any(expected_error_fragment in err for err in validation["errors"])

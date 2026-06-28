import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.power_map_service import (  # noqa: E402
    PERSON_H,
    PERSON_W,
    MergeContext,
    PowerNode,
    _compute_radial_org_layout,
    _estimate_radial_department_size,
    _parse_power_map_intent,
)


def _ctx_for_org() -> MergeContext:
    ctx = MergeContext()
    dept = PowerNode(id="d-sales", name="销售部", node_type="dept", w=300, h=200)
    leader = PowerNode(
        id="u-leader",
        name="张强",
        node_type="user",
        position="销售总监",
        parent_dept_id=dept.id,
        w=PERSON_W,
        h=PERSON_H,
    )
    a = PowerNode(id="u-a", name="李光昭", node_type="user", parent_dept_id=dept.id, w=PERSON_W, h=PERSON_H)
    b = PowerNode(id="u-b", name="艾翔", node_type="user", parent_dept_id=dept.id, w=PERSON_W, h=PERSON_H)
    ctx.all_nodes = [dept, leader, a, b]
    ctx.nodes_by_id = {n.id: n for n in ctx.all_nodes}
    ctx.nodes_by_name = {n.name: n for n in ctx.all_nodes}
    ctx.depts_by_name = {dept.name: dept}
    return ctx


def test_estimate_department_size_scales_with_direct_people_and_child_departments():
    small = _estimate_radial_department_size(direct_people_count=1, child_department_count=0)
    large = _estimate_radial_department_size(direct_people_count=7, child_department_count=2)

    assert large["w"] > small["w"]
    assert large["h"] > small["h"]
    assert small["w"] >= 300
    assert small["h"] >= 200


def test_compute_radial_org_layout_places_leader_above_direct_reports():
    ctx = _ctx_for_org()
    intent = _parse_power_map_intent(
        """
        {
          "departments": [{"name": "销售部", "parent": ""}],
          "people": [
            {"name": "张强", "title": "销售总监", "parent": "销售部"},
            {"name": "李光昭", "parent": "销售部"},
            {"name": "艾翔", "parent": "销售部"}
          ],
          "report_edges": [
            {"source": "李光昭", "target": "张强"},
            {"source": "艾翔", "target": "张强"}
          ]
        }
        """
    )

    result = _compute_radial_org_layout(ctx, intent=intent)
    positions = result["positions"]

    assert positions["u-leader"]["y"] < positions["u-a"]["y"]
    assert positions["u-leader"]["y"] < positions["u-b"]["y"]
    reports_center = (
        positions["u-a"]["x"] + PERSON_W / 2 + positions["u-b"]["x"] + PERSON_W / 2
    ) / 2
    leader_center = positions["u-leader"]["x"] + PERSON_W / 2
    assert abs(leader_center - reports_center) <= 20


def test_compute_radial_org_layout_fans_out_top_level_departments():
    ctx = MergeContext()
    exec_dept = PowerNode(id="d-exec", name="总裁办", node_type="dept", w=300, h=200)
    finance = PowerNode(id="d-fin", name="财务部", node_type="dept", w=300, h=200)
    sales = PowerNode(id="d-sales", name="销售部", node_type="dept", w=300, h=200)
    ceo = PowerNode(id="u-ceo", name="黄宇", node_type="user", parent_dept_id="d-exec", w=PERSON_W, h=PERSON_H)
    cfo = PowerNode(id="u-cfo", name="纪成", node_type="user", parent_dept_id="d-fin", w=PERSON_W, h=PERSON_H)
    sales_head = PowerNode(id="u-sales", name="张强", node_type="user", parent_dept_id="d-sales", w=PERSON_W, h=PERSON_H)
    ctx.all_nodes = [exec_dept, finance, sales, ceo, cfo, sales_head]
    ctx.nodes_by_id = {n.id: n for n in ctx.all_nodes}
    ctx.nodes_by_name = {n.name: n for n in ctx.all_nodes}
    ctx.depts_by_name = {n.name: n for n in ctx.all_nodes if n.node_type == "dept"}
    intent = _parse_power_map_intent(
        """
        {
          "report_edges": [
            {"source": "纪成", "target": "黄宇"},
            {"source": "张强", "target": "黄宇"}
          ]
        }
        """
    )

    result = _compute_radial_org_layout(ctx, intent=intent)
    positions = result["positions"]

    assert positions["d-exec"]["y"] < positions["d-fin"]["y"]
    assert positions["d-exec"]["y"] < positions["d-sales"]["y"]
    assert positions["d-fin"]["x"] < positions["d-sales"]["x"]


def _parallel_department_ctx(count: int) -> MergeContext:
    ctx = MergeContext()
    ctx.all_nodes = [
        PowerNode(
            id=f"d-{index:02d}",
            name=f"部门{index:02d}",
            node_type="dept",
            w=300,
            h=200,
        )
        for index in range(count)
    ]
    ctx.nodes_by_id = {node.id: node for node in ctx.all_nodes}
    ctx.nodes_by_name = {node.name: node for node in ctx.all_nodes}
    ctx.depts_by_name = {node.name: node for node in ctx.all_nodes}
    return ctx


def _boxes_overlap(left: dict, right: dict) -> bool:
    return not (
        left["x"] + left["w"] <= right["x"]
        or right["x"] + right["w"] <= left["x"]
        or left["y"] + left["h"] <= right["y"]
        or right["y"] + right["h"] <= left["y"]
    )


def test_radial_layout_wraps_large_parallel_department_rank():
    ctx = _parallel_department_ctx(30)

    result = _compute_radial_org_layout(ctx)
    positions = result["positions"]
    distinct_rows = {round(item["y"], 3) for item in positions.values()}
    min_x = min(item["x"] for item in positions.values())
    max_x = max(item["x"] + item["w"] for item in positions.values())

    assert len(distinct_rows) >= 2
    assert max_x - min_x < 5000


def test_radial_layout_wrapping_is_deterministic_and_non_overlapping():
    first = _compute_radial_org_layout(_parallel_department_ctx(30))["positions"]
    second = _compute_radial_org_layout(_parallel_department_ctx(30))["positions"]

    assert first == second
    values = list(first.values())
    for index, left in enumerate(values):
        for right in values[index + 1 :]:
            assert not _boxes_overlap(left, right)


def test_radial_layout_keeps_small_parallel_rank_on_one_row():
    result = _compute_radial_org_layout(_parallel_department_ctx(5))

    assert len({round(item["y"], 3) for item in result["positions"].values()}) == 1

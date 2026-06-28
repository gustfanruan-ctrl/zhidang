import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.power_map_service import MergeContext, PowerNode, _tool_relayout  # noqa: E402


def _ctx(nodes: list[PowerNode], edges: list[dict]) -> MergeContext:
    ctx = MergeContext()
    ctx.all_nodes = nodes
    ctx.edges = edges
    ctx.nodes_by_id = {n.id: n for n in nodes}
    ctx.nodes_by_name = {n.name: n for n in nodes}
    ctx.depts_by_name = {n.name: n for n in nodes if n.node_type == "dept"}
    return ctx


def test_relayout_collapses_projected_reporting_cycles_to_same_rank():
    dept = PowerNode(id="d-it", node_type="dept", name="IT")
    simon = PowerNode(id="u-simon", node_type="user", name="Simon", parent_dept_id=dept.id)
    ray = PowerNode(id="u-ray", node_type="user", name="Ray", parent_dept_id=dept.id)
    raymond = PowerNode(id="u-raymond", node_type="user", name="Raymond")
    report = PowerNode(id="u-report", node_type="user", name="Report", parent_dept_id=dept.id)
    ctx = _ctx(
        [dept, simon, ray, raymond, report],
        [
            {"id": "e1", "source_id": "u-simon", "target_id": "u-raymond", "edge_type": "reports_to"},
            {"id": "e2", "source_id": "u-raymond", "target_id": "u-report", "edge_type": "reports_to"},
        ],
    )

    result = _tool_relayout(ctx, {"direction": "TB", "nodesep": 80, "ranksep": 150})

    assert result["ok"] is True
    for node in ctx.all_nodes:
        assert math.isfinite(node.x)
        assert math.isfinite(node.y)
    assert abs((dept.y + dept.h / 2) - (raymond.y + raymond.h / 2)) < 1

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

try:
    from backend.tests.check_geometry import check_geometry_from_nodes
except Exception:
    from tests.check_geometry import check_geometry_from_nodes  # type: ignore


@dataclass
class ToolStep:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    ok: bool = False


@dataclass
class RoundRecord:
    round_no: int
    steps: list[ToolStep] = field(default_factory=list)


class PowerMapContextBuilder:
    def __init__(
        self,
        *,
        focus_limit: int = 16,
        focus_hops: int = 2,
        max_json_nodes: int = 20,
        max_history_rounds: int = 8,
    ) -> None:
        self.focus_limit = focus_limit
        self.focus_hops = focus_hops
        self.max_json_nodes = max_json_nodes
        self.max_history_rounds = max_history_rounds
        self._previous_graph: dict[str, Any] | None = None
        self._round_no = 0
        self._current_round = RoundRecord(round_no=0)
        self._history: list[RoundRecord] = []

    def begin_round(self, round_no: int | None = None) -> None:
        if self._current_round.steps:
            self._history.append(self._current_round)
            self._history = self._history[-self.max_history_rounds :]
        self._round_no = round_no if round_no is not None else (self._round_no + 1)
        self._current_round = RoundRecord(round_no=self._round_no)

    def record_tool_call(self, name: str, args: dict[str, Any] | None = None) -> None:
        self._current_round.steps.append(ToolStep(name=name, args=dict(args or {})))

    def record_tool_result(self, name: str, result: dict[str, Any]) -> None:
        if self._current_round.steps:
            last = self._current_round.steps[-1]
            if last.name == name and not last.result:
                last.result = dict(result or {})
                last.ok = bool((result or {}).get("ok"))
                return
        self._current_round.steps.append(
            ToolStep(name=name, result=dict(result or {}), ok=bool((result or {}).get("ok")))
        )

    def build(self, ctx: Any) -> str:
        graph = _get_graph_state(ctx)
        touched_ids, touched_edge_ids = self._current_touched_ids()
        focus_ids = _choose_focus_ids(
            graph,
            touched_ids=touched_ids,
            limit=self.focus_limit,
            hops=self.focus_hops,
        )
        text = build_pyramid_text(
            graph,
            previous_graph=self._previous_graph,
            focus_ids=focus_ids,
            touched_ids=touched_ids,
            touched_edge_ids=touched_edge_ids,
            history=self._history,
            current_round=self._current_round,
            max_json_nodes=self.max_json_nodes,
        )
        self._previous_graph = graph
        if self._current_round.steps:
            self._history.append(self._current_round)
            self._history = self._history[-self.max_history_rounds :]
            self._current_round = RoundRecord(round_no=self._round_no)
        return text

    def _current_touched_ids(self) -> tuple[set[str], set[str]]:
        tool_calls = [(step.name, step.args) for step in self._current_round.steps]
        tool_results = [step.result for step in self._current_round.steps]
        try:
            from backend.app.services.power_map_service import _extract_touched_ids
        except Exception:
            try:
                from app.services.power_map_service import _extract_touched_ids  # type: ignore
            except Exception:
                return set(), set()
        touched = _extract_touched_ids(tool_calls, tool_results)
        touched_edge_ids = {
            str(step.result.get("edge_id"))
            for step in self._current_round.steps
            if step.result.get("edge_id")
        }
        return touched, touched_edge_ids


def build_pyramid_text(
    graph: dict[str, Any],
    *,
    previous_graph: dict[str, Any] | None,
    focus_ids: list[str],
    touched_ids: set[str],
    touched_edge_ids: set[str],
    history: list[RoundRecord],
    current_round: RoundRecord,
    max_json_nodes: int = 20,
) -> str:
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    node_by_id = {str(n.get("id") or ""): n for n in nodes if str(n.get("id") or "")}
    edge_by_id = {str(e.get("id") or ""): e for e in edges if str(e.get("id") or "")}

    summary_text = _build_summary(nodes, edges, previous_graph, graph)
    mermaid_text = _build_mermaid(nodes, edges, focus_ids, node_by_id)
    detail_json = _build_detail_json(nodes, edges, node_by_id, focus_ids, max_json_nodes)
    analysis_text = _build_analysis(nodes, edges, node_by_id, touched_ids, touched_edge_ids)
    history_text = _build_history(history, current_round)

    return "\n".join(
        [
            "=========================================",
            "LAYER 1: 摘要（必看，固定在最前）",
            "=========================================",
            summary_text,
            "",
            "=========================================",
            "LAYER 2: 拓扑视图（Mermaid，看结构）",
            "=========================================",
            "```mermaid",
            mermaid_text,
            "```",
            "",
            "=========================================",
            "LAYER 3: 详细数据（JSON，需精确时查阅）",
            "=========================================",
            "```json",
            json.dumps(detail_json, ensure_ascii=False, indent=2, default=str),
            "```",
            "",
            "=========================================",
            "LAYER 4: 派生分析（算法预算好的视觉判断）",
            "=========================================",
            analysis_text,
            "",
            "=========================================",
            "LAYER 5: 操作历史（context 衔接用）",
            "=========================================",
            history_text,
        ]
    ).strip()


def _get_graph_state(ctx: Any) -> dict[str, Any]:
    try:
        from backend.app.services.power_map_service import _tool_get_graph_state
    except Exception:
        from app.services.power_map_service import _tool_get_graph_state  # type: ignore
    return _tool_get_graph_state(ctx)


def _node_kind(node: dict[str, Any]) -> str:
    return str(node.get("type") or node.get("node_type") or "")


def _node_label(node: dict[str, Any]) -> str:
    name = str(node.get("name") or node.get("label") or node.get("id") or "").strip()
    extras: list[str] = []
    kind = _node_kind(node)
    if kind:
        extras.append(kind)
    role = str(node.get("role") or "").strip()
    if role:
        extras.append(f"role={role}")
    position = str(node.get("position") or "").strip()
    if position:
        extras.append(f"position={position}")
    suffix = f" [{' | '.join(extras)}]" if extras else ""
    return f"{name}{suffix}"


def _rect(node: dict[str, Any]) -> tuple[float, float, float, float] | None:
    x = node.get("x")
    y = node.get("y")
    w = node.get("width", node.get("w"))
    h = node.get("height", node.get("h"))
    if x is None or y is None or w is None or h is None:
        return None
    try:
        left = float(x)
        top = float(y)
        width = float(w)
        height = float(h)
    except Exception:
        return None
    return left, top, left + width, top + height


def _build_summary(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    previous_graph: dict[str, Any] | None,
    current_graph: dict[str, Any],
) -> str:
    dept_count = sum(1 for n in nodes if _node_kind(n) in {"dept", "department"})
    person_count = sum(1 for n in nodes if _node_kind(n) in {"user", "person"})
    depth = max((int(n.get("depth", 0) or 0) for n in nodes), default=0) + 1 if nodes else 0
    diff = _diff_graph(previous_graph, current_graph)
    layout = _geometry_summary(nodes, edges, touched_ids=None, touched_edge_ids=None)

    change_parts = []
    if diff["added_nodes"]:
        change_parts.append(f"新增 {diff['added_nodes']} 节点")
    if diff["removed_nodes"]:
        change_parts.append(f"删除 {diff['removed_nodes']} 节点")
    if diff["added_edges"]:
        change_parts.append(f"新增 {diff['added_edges']} 边")
    if diff["removed_edges"]:
        change_parts.append(f"删除 {diff['removed_edges']} 边")
    if diff["moved_nodes"]:
        change_parts.append(f"移动 {diff['moved_nodes']} 个节点")
    if not change_parts:
        change_parts.append("无结构变化")

    lines = [
        f"图概览：{len(nodes)} 节点，{len(edges)} 边，{depth} 层级（部门 {dept_count} / 人员 {person_count}）",
        "本轮变化：" + "，".join(change_parts),
        f"布局状态：{layout['short']}",
    ]
    return "\n".join(lines)


def _diff_graph(previous_graph: dict[str, Any] | None, current_graph: dict[str, Any]) -> dict[str, int]:
    prev_nodes = {str(n.get("id") or ""): n for n in (previous_graph or {}).get("nodes") or []}
    curr_nodes = {str(n.get("id") or ""): n for n in current_graph.get("nodes") or []}
    prev_edges = {str(e.get("id") or ""): e for e in (previous_graph or {}).get("edges") or []}
    curr_edges = {str(e.get("id") or ""): e for e in current_graph.get("edges") or []}

    moved_nodes = 0
    for node_id, node in curr_nodes.items():
        old = prev_nodes.get(node_id)
        if not old:
            continue
        old_state = (
            old.get("x"),
            old.get("y"),
            old.get("parent_id"),
            old.get("parent_dept_id"),
            old.get("position"),
            old.get("role"),
        )
        new_state = (
            node.get("x"),
            node.get("y"),
            node.get("parent_id"),
            node.get("parent_dept_id"),
            node.get("position"),
            node.get("role"),
        )
        if old_state != new_state:
            moved_nodes += 1

    return {
        "added_nodes": len([nid for nid in curr_nodes if nid not in prev_nodes]),
        "removed_nodes": len([nid for nid in prev_nodes if nid not in curr_nodes]),
        "added_edges": len([eid for eid in curr_edges if eid not in prev_edges]),
        "removed_edges": len([eid for eid in prev_edges if eid not in curr_edges]),
        "moved_nodes": moved_nodes,
    }


def _build_mermaid(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    focus_ids: list[str],
    node_by_id: dict[str, dict[str, Any]],
) -> str:
    focus = {node_id for node_id in focus_ids if node_id in node_by_id}
    if not focus:
        focus = {
            node_id
            for node_id, node in node_by_id.items()
            if not str(node.get("parent_id") or node.get("parent_dept_id") or "")
        }
    for node_id in list(focus):
        node = node_by_id.get(node_id)
        if not node:
            continue
        parent_id = str(node.get("parent_id") or node.get("parent_dept_id") or "")
        if parent_id in node_by_id:
            focus.add(parent_id)
        for child_id in node.get("children_ids") or []:
            if str(child_id) in node_by_id:
                focus.add(str(child_id))

    rendered_ids = [node_id for node_id in focus if node_id in node_by_id]
    alias_map = {node_id: f"n{i+1}" for i, node_id in enumerate(rendered_ids)}
    lines = ["graph TD"]
    for node_id in rendered_ids:
        label = _node_label(node_by_id[node_id]).replace('"', "'")
        lines.append(f'    {alias_map[node_id]}["{label}"]')
    for edge in edges:
        source_id = str(edge.get("source_id") or "")
        target_id = str(edge.get("target_id") or "")
        if source_id in alias_map and target_id in alias_map:
            edge_type = str(edge.get("edge_type") or "reports_to")
            lines.append(f"    {alias_map[source_id]} -->|{edge_type}| {alias_map[target_id]}")
    if len(rendered_ids) < len(node_by_id):
        lines.append(f"    %% focus-only view: {len(rendered_ids)}/{len(node_by_id)} nodes")
    return "\n".join(lines)


def _build_detail_json(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    focus_ids: list[str],
    max_json_nodes: int,
) -> dict[str, Any]:
    ordered_ids = [node_id for node_id in focus_ids if node_id in node_by_id]
    if not ordered_ids:
        ordered_ids = [str(node.get("id") or "") for node in nodes if str(node.get("id") or "")]
    ordered_ids = ordered_ids[:max_json_nodes]
    focus_nodes = [node_by_id[node_id] for node_id in ordered_ids if node_id in node_by_id]
    focus_set = {str(node.get("id") or "") for node in focus_nodes}
    focus_edges = [
        edge
        for edge in edges
        if str(edge.get("source_id") or "") in focus_set and str(edge.get("target_id") or "") in focus_set
    ]
    return {
        "scope": {
            "mode": "focus",
            "node_count": len(focus_nodes),
            "edge_count": len(focus_edges),
            "omitted_nodes": max(len(nodes) - len(focus_nodes), 0),
            "omitted_edges": max(len(edges) - len(focus_edges), 0),
        },
        "nodes": focus_nodes,
        "edges": focus_edges,
        "all_node_count": len(nodes),
        "all_edge_count": len(edges),
    }


def _build_analysis(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    touched_ids: set[str],
    touched_edge_ids: set[str],
) -> str:
    layout = _geometry_summary(
        nodes,
        edges,
        touched_ids=touched_ids or None,
        touched_edge_ids=touched_edge_ids or None,
    )
    lines = ["布局问题："]

    conflict_lines = 0
    for conflict in layout["conflicts"][:5]:
        left = str(conflict.get("node_a") or conflict.get("person") or conflict.get("dept") or "?")
        right = str(conflict.get("node_b") or conflict.get("parent_dept") or "?")
        severity = str(conflict.get("severity") or "INFO")
        lines.append(f"- [{severity}] {left} / {right}：{str(conflict.get('message') or '').strip()}")
        conflict_lines += 1

    for edge_cross in layout["crossings"][: max(0, 5 - conflict_lines)]:
        eid1, eid2, s1, t1, s2, t2 = edge_cross
        lines.append(f"- [CROSS] 边 {eid1}({s1}->{t1}) 与边 {eid2}({s2}->{t2}) 发生交叉")

    if layout["density"]:
        hotspot = layout["density"][0]
        lines.append(
            f"- [DENSE] 网格 {hotspot['grid']} 内有 {hotspot['count']} 个节点，建议拉开间距"
        )

    if layout["isolated"]:
        isolated_labels = [
            _node_label(node_by_id[node_id]) for node_id in layout["isolated"] if node_id in node_by_id
        ]
        lines.append("- [ISOLATED] 孤立节点：" + "，".join(isolated_labels[:5]))

    cycle_nodes = _detect_reports_to_cycle(nodes, edges)
    if cycle_nodes:
        lines.append("- [CYCLE] reports_to 关系疑似成环：" + " -> ".join(cycle_nodes[:6]))

    if len(lines) == 1:
        lines.append("- 未检测到明显布局问题")
    lines.append(f"可读性评分：{layout['score']}/100")
    return "\n".join(lines)


def _segment_intersection(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
) -> bool:
    def orient(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1 = orient(a1, a2, b1)
    o2 = orient(a1, a2, b2)
    o3 = orient(b1, b2, a1)
    o4 = orient(b1, b2, a2)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def _geometry_summary(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    touched_ids: set[str] | None,
    touched_edge_ids: set[str] | None,
) -> dict[str, Any]:
    report = check_geometry_from_nodes(
        nodes,
        edges,
        touched_ids=touched_ids,
        touched_edge_ids=touched_edge_ids,
    )
    conflicts = list(report.get("conflicts") or [])
    node_by_id = {str(node.get("id") or ""): node for node in nodes if str(node.get("id") or "")}

    crossings: list[tuple[str, str, str, str, str, str]] = []
    edge_pairs = [
        (
            str(edge.get("id") or ""),
            str(edge.get("source_id") or ""),
            str(edge.get("target_id") or ""),
        )
        for edge in edges
    ]
    for i in range(len(edge_pairs)):
        edge_id_1, source_1, target_1 = edge_pairs[i]
        source_node_1 = node_by_id.get(source_1)
        target_node_1 = node_by_id.get(target_1)
        rect_s1 = _rect(source_node_1) if source_node_1 else None
        rect_t1 = _rect(target_node_1) if target_node_1 else None
        if not rect_s1 or not rect_t1:
            continue
        point_s1 = ((rect_s1[0] + rect_s1[2]) / 2, (rect_s1[1] + rect_s1[3]) / 2)
        point_t1 = ((rect_t1[0] + rect_t1[2]) / 2, (rect_t1[1] + rect_t1[3]) / 2)

        for j in range(i + 1, len(edge_pairs)):
            edge_id_2, source_2, target_2 = edge_pairs[j]
            if len({source_1, target_1, source_2, target_2}) < 4:
                continue
            source_node_2 = node_by_id.get(source_2)
            target_node_2 = node_by_id.get(target_2)
            rect_s2 = _rect(source_node_2) if source_node_2 else None
            rect_t2 = _rect(target_node_2) if target_node_2 else None
            if not rect_s2 or not rect_t2:
                continue
            point_s2 = ((rect_s2[0] + rect_s2[2]) / 2, (rect_s2[1] + rect_s2[3]) / 2)
            point_t2 = ((rect_t2[0] + rect_t2[2]) / 2, (rect_t2[1] + rect_t2[3]) / 2)
            if _segment_intersection(point_s1, point_t1, point_s2, point_t2):
                crossings.append((edge_id_1, edge_id_2, source_1, target_1, source_2, target_2))

    density = _density_hotspots(nodes)
    isolated = _isolated_nodes(nodes, edges)
    score = 100
    score -= min(sum(1 for item in conflicts if item.get("severity") == "CRITICAL") * 12, 36)
    score -= min(sum(1 for item in conflicts if item.get("severity") == "HIGH") * 8, 24)
    score -= min(len(crossings) * 3, 18)
    score -= min(len(density) * 2, 10)
    score -= min(len(isolated) * 2, 10)
    score = max(score, 0)

    short = "✅ 正常"
    parts = []
    if conflicts:
        parts.append(f"{len(conflicts)} 处几何冲突")
    if crossings:
        parts.append(f"{len(crossings)} 处边交叉")
    if isolated:
        parts.append(f"{len(isolated)} 个孤立节点")
    if parts:
        short = "⚠️ " + "，".join(parts)

    return {
        "short": short,
        "score": score,
        "conflicts": conflicts,
        "crossings": crossings,
        "density": density,
        "isolated": isolated,
    }


def _density_hotspots(nodes: list[dict[str, Any]], cell_w: int = 320, cell_h: int = 240) -> list[dict[str, Any]]:
    buckets: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for node in nodes:
        rect = _rect(node)
        if not rect:
            continue
        cx = (rect[0] + rect[2]) / 2
        cy = (rect[1] + rect[3]) / 2
        key = (int(cx // cell_w), int(cy // cell_h))
        buckets.setdefault(key, []).append(node)
    hotspots = []
    for (gx, gy), bucket in buckets.items():
        if len(bucket) < 4:
            continue
        hotspots.append(
            {
                "grid": [gx, gy],
                "count": len(bucket),
                "nodes": [str(node.get("id") or "") for node in bucket[:8]],
            }
        )
    hotspots.sort(key=lambda item: (-item["count"], item["grid"]))
    return hotspots[:5]


def _isolated_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    incoming = {str(node.get("id") or ""): 0 for node in nodes}
    outgoing = {str(node.get("id") or ""): 0 for node in nodes}
    children = {str(node.get("id") or ""): list(node.get("children_ids") or []) for node in nodes}
    for edge in edges:
        source_id = str(edge.get("source_id") or "")
        target_id = str(edge.get("target_id") or "")
        if source_id in outgoing:
            outgoing[source_id] += 1
        if target_id in incoming:
            incoming[target_id] += 1
    isolated = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        parent_id = str(node.get("parent_id") or node.get("parent_dept_id") or "")
        if incoming.get(node_id, 0) == 0 and outgoing.get(node_id, 0) == 0 and not children.get(node_id) and not parent_id:
            isolated.append(node_id)
    return isolated[:10]


def _detect_reports_to_cycle(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if str(edge.get("edge_type") or "") != "reports_to":
            continue
        source_id = str(edge.get("source_id") or "")
        target_id = str(edge.get("target_id") or "")
        if source_id and target_id:
            adjacency.setdefault(source_id, []).append(target_id)

    visited: set[str] = set()
    stack: set[str] = set()
    path: list[str] = []

    def dfs(node_id: str) -> list[str] | None:
        visited.add(node_id)
        stack.add(node_id)
        path.append(node_id)
        for nxt in adjacency.get(node_id, []):
            if nxt not in visited:
                found = dfs(nxt)
                if found:
                    return found
            elif nxt in stack:
                start_idx = path.index(nxt)
                return path[start_idx:] + [nxt]
        stack.remove(node_id)
        path.pop()
        return None

    for node in nodes:
        node_id = str(node.get("id") or "")
        if node_id and node_id not in visited:
            found = dfs(node_id)
            if found:
                node_by_id = {str(n.get("id") or ""): n for n in nodes}
                return [_node_label(node_by_id.get(item, {"id": item})) for item in found]
    return []


def _build_history(history: list[RoundRecord], current_round: RoundRecord) -> str:
    rounds = list(history[-7:])
    if current_round.steps:
        rounds.append(current_round)
    if not rounds:
        return "本会话已执行：\n- 暂无操作历史"

    rows = ["本会话已执行："]
    index = 1
    for round_record in rounds:
        for step in round_record.steps:
            args_preview = []
            for key in ("node_id", "dept_id", "container_id", "edge_id", "source_id", "target_id", "name", "x", "y"):
                if key in step.args and step.args.get(key) not in ("", None):
                    args_preview.append(f"{key}={step.args.get(key)!r}")
            result_ref = step.result.get("node_id") or step.result.get("edge_id") or step.result.get("container_id") or ""
            suffix = f" → {result_ref}" if result_ref else ""
            status = "成功" if step.ok else "失败"
            rows.append(f"{index}. [r{round_record.round_no}] {step.name}({', '.join(args_preview)}) [{status}]{suffix}")
            index += 1
    return "\n".join(rows)


def _choose_focus_ids(
    graph: dict[str, Any],
    touched_ids: set[str],
    limit: int,
    hops: int,
) -> list[str]:
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    node_by_id = {str(node.get("id") or ""): node for node in nodes if str(node.get("id") or "")}
    if not node_by_id:
        return []

    parent_map: dict[str, str] = {}
    child_map: dict[str, list[str]] = {}
    neighbor_map: dict[str, set[str]] = {node_id: set() for node_id in node_by_id}
    for node in nodes:
        node_id = str(node.get("id") or "")
        parent_id = str(node.get("parent_id") or node.get("parent_dept_id") or "")
        if parent_id:
            parent_map[node_id] = parent_id
            child_map.setdefault(parent_id, []).append(node_id)
            if parent_id in neighbor_map:
                neighbor_map[parent_id].add(node_id)
                neighbor_map[node_id].add(parent_id)
    for edge in edges:
        source_id = str(edge.get("source_id") or "")
        target_id = str(edge.get("target_id") or "")
        if source_id in neighbor_map and target_id in neighbor_map:
            neighbor_map[source_id].add(target_id)
            neighbor_map[target_id].add(source_id)

    if touched_ids:
        seeds = [node_id for node_id in touched_ids if node_id in node_by_id]
    else:
        seeds = [
            node_id
            for node_id, node in node_by_id.items()
            if not str(node.get("parent_id") or node.get("parent_dept_id") or "")
        ]
        seeds.sort(
            key=lambda node_id: (
                0 if _node_kind(node_by_id[node_id]) in {"dept", "department"} else 1,
                str(node_by_id[node_id].get("name") or node_id),
            )
        )
    if not seeds:
        seeds = [next(iter(node_by_id))]

    chosen: list[str] = []
    seen: set[str] = set()
    frontier = list(seeds)
    for _ in range(max(hops, 1) + 1):
        next_frontier: list[str] = []
        for node_id in frontier:
            if node_id in seen or node_id not in node_by_id:
                continue
            seen.add(node_id)
            chosen.append(node_id)
            if len(chosen) >= limit:
                return chosen[:limit]
            for neighbor in sorted(neighbor_map.get(node_id, set())):
                if neighbor not in seen:
                    next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    for node_id in sorted(node_by_id, key=lambda item: (item not in touched_ids, str(node_by_id[item].get("name") or item))):
        if node_id not in seen:
            chosen.append(node_id)
            if len(chosen) >= limit:
                break
    return chosen[:limit]

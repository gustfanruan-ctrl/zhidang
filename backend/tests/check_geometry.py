#!/usr/bin/env python3
"""
几何冲突自动检测脚本。
输入: ctx JSON 文件（nodes + edges），或 session_id（需能访问 _SESSION_STORE）
输出: 冲突清单

检测规则（只检查直接父子包裹关系，不追溯祖先）：
A. 人员未完全在父容器内（HIGH）
B. 子部门未完全在父部门内（HIGH）
C. 同级容器（相同 parent_id）矩形重叠（CRITICAL）
D. 同容器内人员节点重叠（MEDIUM）
"""

import json
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class BBox:
    id: str
    name: str
    node_type: str  # "dept" | "user" (MergeContext canonical)
    x: float
    y: float
    width: float
    height: float
    parent_dept_id: Optional[str] = None

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return (self.left, self.top, self.right, self.bottom)

    def area(self) -> float:
        return self.width * self.height


def overlap_rect(r1: tuple[float, float, float, float],
                 r2: tuple[float, float, float, float]) -> tuple[float, float, float, float] | None:
    """返回重叠矩形 (left, top, right, bottom)，无重叠返回 None"""
    left = max(r1[0], r2[0])
    top = max(r1[1], r2[1])
    right = min(r1[2], r2[2])
    bottom = min(r1[3], r2[3])
    if left < right and top < bottom:
        return (left, top, right, bottom)
    return None


def overlap_area(r1: tuple[float, float, float, float],
                 r2: tuple[float, float, float, float]) -> float:
    ov = overlap_rect(r1, r2)
    if ov is None:
        return 0.0
    return (ov[2] - ov[0]) * (ov[3] - ov[1])


def point_in_rect(x: float, y: float, rect: tuple[float, float, float, float]) -> bool:
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def parse_ctx(data: dict) -> tuple[list[BBox], list[str]]:
    """Parse ctx JSON into BBox list and warnings."""
    nodes = data.get("nodes", [])
    warnings: list[str] = []
    bboxes: list[BBox] = []

    for n in nodes:
        ntype = n.get("type", n.get("node_type", ""))
        nid = n.get("id", "")
        nname = n.get("name", n.get("label", nid))
        nx = float(n.get("x", 0) or 0)
        ny = float(n.get("y", 0) or 0)
        nw = float(n.get("width", n.get("w", 160)) or 160)
        nh = float(n.get("height", n.get("h", 72)) or 72)
        parent = n.get("parent_dept_id") or n.get("parent_id") or n.get("parent_dept") or n.get("par_id") or ""

        if ntype in ("dept", "department"):
            bboxes.append(BBox(
                id=nid, name=nname, node_type="dept",
                x=nx, y=ny, width=nw, height=nh,
                parent_dept_id=parent or None,
            ))
        elif ntype in ("user", "person"):
            bboxes.append(BBox(
                id=nid, name=nname, node_type="user",
                x=nx, y=ny, width=nw, height=nh,
                parent_dept_id=parent or None,
            ))
        else:
            # system/org — skip collision checks (no geometry)
            pass

    if not bboxes:
        warnings.append("no nodes found in ctx")

    return bboxes, warnings


def parse_edges(data: dict) -> list[dict]:
    """Parse edges dict into normalized list [{id, from, to}]."""
    raw = data.get("edges", [])
    result = []
    for e in raw:
        result.append({
            "id": e.get("id", ""),
            "from": e.get("from", e.get("source", e.get("source_id", ""))),
            "to": e.get("to", e.get("target", e.get("target_id", ""))),
        })
    return result


def check_geometry_from_nodes(
    nodes: list[dict],
    edges: list[dict],
    touched_ids: set[str] | None = None,
    touched_edge_ids: set[str] | None = None,
) -> dict:
    """Run geometry check on node/edge dicts. Returns the full report dict."""
    data = {"nodes": nodes, "edges": edges}
    bboxes, _warnings = parse_ctx(data)
    active_edges = parse_edges(data)
    return find_conflicts(bboxes, active_edges, touched_ids, touched_edge_ids)


def _overflow_list(inner: BBox, outer: BBox) -> list[str]:
    out: list[str] = []
    if inner.left < outer.left:
        out.append(f"左溢出 {outer.left - inner.left:.0f}px")
    if inner.right > outer.right:
        out.append(f"右溢出 {inner.right - outer.right:.0f}px")
    if inner.top < outer.top:
        out.append(f"上溢出 {outer.top - inner.top:.0f}px")
    if inner.bottom > outer.bottom:
        out.append(f"下溢出 {inner.bottom - outer.bottom:.0f}px")
    return out


def find_conflicts(
    bboxes: list[BBox],
    edges: list[dict] | None = None,
    touched_ids: set[str] | None = None,
    touched_edge_ids: set[str] | None = None,
) -> dict:
    """Run all 4 geometry checks (A/B/C/D). Returns structured report.

    If touched_ids is not None, only conflicts involving at least one of the
    given ids are returned.
    """
    departments = [b for b in bboxes if b.node_type == "dept"]
    persons = [b for b in bboxes if b.node_type == "user"]

    report: dict = {
        "total_departments": len(departments),
        "total_persons": len(persons),
        "conflicts": [],
    }

    is_full_scan = touched_ids is None
    touched = set(touched_ids or set())

    def _in_scope(*ids: str) -> bool:
        if is_full_scan:
            return True
        return any(i in touched for i in ids if i)

    # ── Rule A: 人员未完全在父容器内（HIGH）──
    for p in persons:
        if not p.parent_dept_id:
            continue
        parent = _find_dept_bbox(departments, p.parent_dept_id)
        if parent is None:
            continue
        if not _in_scope(p.id, parent.id):
            continue
        inside = (p.left >= parent.left and p.top >= parent.top
                  and p.right <= parent.right and p.bottom <= parent.bottom)
        if not inside:
            overflow = _overflow_list(p, parent)
            report["conflicts"].append({
                "rule": "A",
                "severity": "HIGH",
                "message": f"{p.name} 未完全在父容器 {parent.name} 内",
                "person": p.name,
                "parent_dept": parent.name,
                "node_a": p.name,
                "node_b": parent.name,
                "person_rect": {"x": p.x, "y": p.y, "w": p.width, "h": p.height},
                "container_rect": {"x": parent.x, "y": parent.y, "w": parent.width, "h": parent.height},
                "overflow": overflow,
            })

    # ── Rule B: 子部门未完全在父部门内（HIGH）──
    for d in departments:
        pid = (d.parent_dept_id or "").strip()
        if not pid:
            continue
        parent = _find_dept_bbox(departments, pid)
        if parent is None:
            continue
        if not _in_scope(d.id, parent.id):
            continue
        inside = (d.left >= parent.left and d.top >= parent.top
                  and d.right <= parent.right and d.bottom <= parent.bottom)
        if not inside:
            overflow = _overflow_list(d, parent)
            report["conflicts"].append({
                "rule": "B",
                "severity": "HIGH",
                "message": f"子部门 {d.name} 未完全在父部门 {parent.name} 内",
                "dept": d.name,
                "parent_dept": parent.name,
                "node_a": d.name,
                "node_b": parent.name,
                "dept_rect": {"x": d.x, "y": d.y, "w": d.width, "h": d.height},
                "container_rect": {"x": parent.x, "y": parent.y, "w": parent.width, "h": parent.height},
                "overflow": overflow,
            })

    # ── Rule C: 同级容器重叠（相同 parent_id，包括都为空的顶层兄弟）（CRITICAL）──
    for i in range(len(departments)):
        for j in range(i + 1, len(departments)):
            a, b = departments[i], departments[j]
            a_pid = (a.parent_dept_id or "").strip()
            b_pid = (b.parent_dept_id or "").strip()
            if a_pid != b_pid:
                continue  # 不同级 — 嵌套包含不算重叠
            if not _in_scope(a.id, b.id):
                continue
            area = overlap_area(a.rect, b.rect)
            if area > 0:
                ov = overlap_rect(a.rect, b.rect)
                report["conflicts"].append({
                    "rule": "C",
                    "severity": "CRITICAL",
                    "message": f"{a.name} 与 {b.name} 容器重叠，重叠面积 {int(area)} px²",
                    "node_a": a.name,
                    "node_b": b.name,
                    "a_rect": {"x": a.x, "y": a.y, "w": a.width, "h": a.height},
                    "b_rect": {"x": b.x, "y": b.y, "w": b.width, "h": b.height},
                    "overlap_area_px2": int(area),
                    "overlap_rect": {
                        "x": ov[0], "y": ov[1],
                        "w": ov[2] - ov[0], "h": ov[3] - ov[1],
                    } if ov else None,
                })

    # ── Rule D: 同容器内人员重叠（MEDIUM）──
    by_parent: dict[str, list[BBox]] = {}
    for p in persons:
        key = p.parent_dept_id or "__orphan__"
        by_parent.setdefault(key, []).append(p)

    for parent_id, group in by_parent.items():
        parent_name = _find_dept_name(departments, parent_id) if parent_id != "__orphan__" else "(无容器)"
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if not _in_scope(a.id, b.id):
                    continue
                area = overlap_area(a.rect, b.rect)
                if area > 0:
                    report["conflicts"].append({
                        "rule": "D",
                        "severity": "MEDIUM",
                        "message": f"{a.name} 与 {b.name} 在 {parent_name} 内重叠",
                        "parent_dept": parent_name,
                        "person_a": a.name,
                        "person_b": b.name,
                        "node_a": a.name,
                        "node_b": b.name,
                        "a_rect": {"x": a.x, "y": a.y, "w": a.width, "h": a.height},
                        "b_rect": {"x": b.x, "y": b.y, "w": b.width, "h": b.height},
                        "overlap_area_px2": int(area),
                    })

    report["total_conflicts"] = len(report["conflicts"])
    return report


def _find_dept_bbox(departments: list[BBox], dept_id: str) -> BBox | None:
    for d in departments:
        if d.id == dept_id:
            return d
    return None


def _find_dept_name(departments: list[BBox], dept_id: str) -> str:
    d = _find_dept_bbox(departments, dept_id)
    return d.name if d else dept_id


# ── CLI ──

def _parse_args() -> tuple[dict, set[str] | None, set[str] | None]:
    if len(sys.argv) < 2:
        print("Usage: python3 check_geometry.py <ctx.json> [--touched-ids n1,n2] [--touched-edge-ids e1,e2]", file=sys.stderr)
        sys.exit(1)

    data: dict = {}
    touched_ids: set[str] | None = None
    touched_edge_ids: set[str] | None = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--touched-ids" and i + 1 < len(args):
            touched_ids = set(args[i + 1].split(",")) if args[i + 1] else set()
            i += 2
        elif args[i] == "--touched-edge-ids" and i + 1 < len(args):
            touched_edge_ids = set(args[i + 1].split(",")) if args[i + 1] else set()
            i += 2
        elif args[i].startswith("--"):
            print(f"Unknown flag: {args[i]}", file=sys.stderr)
            sys.exit(1)
        else:
            with open(args[i]) as f:
                data = json.load(f)
            i += 1

    if not data:
        print("ERROR: no ctx file provided", file=sys.stderr)
        sys.exit(1)

    return data, touched_ids, touched_edge_ids


def main():
    data, touched_ids, touched_edge_ids = _parse_args()

    _bboxes, warnings = parse_ctx(data)
    for w in warnings:
        print(f"⚠️  {w}")

    report = check_geometry_from_nodes(
        data.get("nodes", []),
        data.get("edges", []),
        touched_ids,
        touched_edge_ids,
    )

    print(f"\n{'='*60}")
    print(f"几何冲突检测报告")
    print(f"{'='*60}")
    print(f"部门: {report['total_departments']}  人员: {report['total_persons']}  冲突: {report['total_conflicts']}")
    print()

    if report["total_conflicts"] == 0:
        print("未检测到几何冲突")
    else:
        for i, c in enumerate(report["conflicts"], 1):
            sev = c["severity"]
            sev_icon = "🔴" if sev == "CRITICAL" else "🟠" if sev == "HIGH" else "🟡"
            rule = c.get("rule", "?")
            print(f"{sev_icon} [{i}] Rule {rule} ({sev}) — {c.get('message', '')}")
            if rule == "C":
                ov = c.get("overlap_rect") or {}
                print(f"    重叠面积: {c.get('overlap_area_px2', 0):,} px²")
                if ov:
                    print(f"    重叠区域: ({ov['x']:.0f}, {ov['y']:.0f}) {ov['w']:.0f}×{ov['h']:.0f}")
                print(f"    A: ({c['a_rect']['x']:.0f},{c['a_rect']['y']:.0f}) {c['a_rect']['w']:.0f}×{c['a_rect']['h']:.0f}")
                print(f"    B: ({c['b_rect']['x']:.0f},{c['b_rect']['y']:.0f}) {c['b_rect']['w']:.0f}×{c['b_rect']['h']:.0f}")
            elif rule == "A":
                print(f"    {c['person']} 超出 {c['parent_dept']}: {', '.join(c.get('overflow', []))}")
            elif rule == "B":
                print(f"    {c['dept']} 超出 {c['parent_dept']}: {', '.join(c.get('overflow', []))}")
            elif rule == "D":
                print(f"    {c['parent_dept']}: {c['person_a']} ↔ {c['person_b']} ({c.get('overlap_area_px2', 0):,} px²)")
            print()

    sys.exit(1 if report["total_conflicts"] > 0 else 0)


if __name__ == "__main__":
    main()

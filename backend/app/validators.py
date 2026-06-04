from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any


def sort_by_confidence(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(operations, key=lambda op: op.get('confidence', 0))


def check_duplicates(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for i, op in enumerate(operations):
        groups.setdefault(op.get('type', ''), []).append((i, op))
    for op_type, items in groups.items():
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                i, op_a = items[a]
                j, op_b = items[b]
                text_a = op_a.get('data', {}).get('summary') or op_a.get('data', {}).get('title') or ''
                text_b = op_b.get('data', {}).get('summary') or op_b.get('data', {}).get('title') or ''
                sim = SequenceMatcher(None, text_a, text_b).ratio()
                if sim >= 0.7:
                    warnings.append({'rule': 'duplicate_suspect', 'indices': [i, j], 'message': f'与第 {j+1} 条操作疑似重复（相似度 {sim:.0%}）', 'severity': 'warning'})
    return warnings


def check_consistency(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for i, op in enumerate(operations):
        data = op.get('data', {})
        updates = op.get('updates', {})
        if op.get('type') == 'new_expectation':
            status = data.get('status', '')
            progress = data.get('progress_note', '')
            if status == '未启动' and str(progress).strip():
                warnings.append({'rule': 'status_progress_mismatch', 'indices': [i], 'message': '状态为“未启动”但填写了进度说明，请确认是否应为“进行中”', 'severity': 'warning'})
        if op.get('type') == 'update_expectation':
            new_status = updates.get('status', '')
            append_progress = updates.get('append_progress', '')
            if new_status == '未启动' and str(append_progress).strip():
                warnings.append({'rule': 'status_progress_mismatch', 'indices': [i], 'message': '状态设为“未启动”但追加了进度，请确认状态是否正确', 'severity': 'warning'})
    return warnings


def mark_low_confidence(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for i, op in enumerate(operations):
        c = op.get('confidence', 0)
        if c < 0.7:
            warnings.append({'rule': 'low_confidence', 'indices': [i], 'message': f'置信度较低（{c:.0%}），请重点审核', 'severity': 'warning'})
    return warnings


def check_coverage(extraction_result: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    extracted_exp_count = len(extraction_result.get('expectations', []))
    extracted_sce_count = len(extraction_result.get('scenarios', []))
    op_exp_count = sum(1 for op in operations if 'expectation' in op.get('type', ''))
    op_sce_count = sum(1 for op in operations if 'scenario' in op.get('type', ''))
    gaps = []
    if op_exp_count < extracted_exp_count:
        gaps.append(f'{extracted_exp_count - op_exp_count} 条预期')
    if op_sce_count < extracted_sce_count:
        gaps.append(f'{extracted_sce_count - op_sce_count} 条场景')
    if gaps:
        return {'has_gap': True, 'message': f"有 {'、'.join(gaps)} 未生成操作指令，可能被遗漏，请核对原文"}
    return {'has_gap': False, 'message': None}


def validate_operations(extraction_result: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_ops = sort_by_confidence(operations)
    warnings = []
    warnings.extend(check_duplicates(sorted_ops))
    warnings.extend(check_consistency(sorted_ops))
    warnings.extend(mark_low_confidence(sorted_ops))
    coverage = check_coverage(extraction_result, sorted_ops)
    return {'operations': sorted_ops, 'warnings': warnings, 'coverage': coverage}

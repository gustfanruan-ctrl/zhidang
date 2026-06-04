from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import SystemConfig


def build_expectation_row(data: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(data)


def build_scenario_row(data: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(data)


def merge_and_write(existing_expectations: list[dict[str, Any]], existing_scenarios: list[dict[str, Any]], operations: list[dict[str, Any]]) -> dict[str, Any]:
    merged_exp = deepcopy(existing_expectations)
    merged_sce = deepcopy(existing_scenarios)
    for op in operations:
        if op.get('type') == 'new_expectation':
            merged_exp.append(build_expectation_row(op.get('data', {})))
        elif op.get('type') == 'update_expectation':
            for row in merged_exp:
                if row.get('_id') == op.get('match_id'):
                    row.update(op.get('updates', {}))
        elif op.get('type') == 'new_scenario':
            merged_sce.append(build_scenario_row(op.get('data', {})))
        elif op.get('type') == 'update_scenario':
            for row in merged_sce:
                if row.get('_id') == op.get('match_id'):
                    row.update(op.get('updates', {}))
    return {'expectations': merged_exp, 'scenarios': merged_sce}

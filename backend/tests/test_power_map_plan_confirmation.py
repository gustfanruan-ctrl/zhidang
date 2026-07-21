import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import power_map_service  # noqa: E402
from app.services.power_map_service import (  # noqa: E402
    HarnessEvent,
    MergeContext,
    PowerMapPlanDraft,
    PowerNode,
    _drop_plan,
    _drop_session,
    _execute_confirmed_plan_preview,
    _get_plan,
    _get_session,
    _run_llm_tool_loop,
    _layout_execution_tools,
    _parse_power_map_intent,
    _store_session,
    _store_plan,
    _tool_arrange_horizontally,
    _tool_arrange_vertically,
    _tool_check_geometry,
    _tool_resize_container,
    _validate_sandbox_render_state,
    commit_power_map_session,
    confirm_power_map_plan,
    discard_power_map_session,
    plan_power_map_v2,
)


def _tool_names() -> set[str]:
    return {
        str(tool.get("function", {}).get("name") or "")
        for tool in _layout_execution_tools()
    }


def test_layout_execution_tool_whitelist_excludes_structure_and_writes():
    names = _tool_names()

    assert {
        "get_node_geometry",
        "place_node",
        "move_dept_with_children",
        "resize_container",
        "fit_container_to_children",
        "arrange_horizontally",
        "arrange_vertically",
        "check_collisions",
        "check_geometry",
        "validate_structure",
    }.issubset(names)
    assert names.isdisjoint({
        "save_state",
        "create_node",
        "delete_node",
        "update_node",
        "set_parent",
        "create_edge",
        "delete_edge",
        "update_edge",
        "set_edge_remark",
        "relayout",
    })


class _LoopConfig:
    power_map_llm_model = "test-model"
    nl_chat_model = "test-model"


def test_layout_text_fallback_rejects_disallowed_tools_before_dispatch(monkeypatch):
    ctx = _layout_ctx()
    ctx.last_screenshot_url = "data:image/png;base64," + "A" * 512
    dangerous_calls = []

    class _FallbackClient:
        def __init__(self):
            self.calls = 0
            self.fallback_system = ""

        async def messages_create_with_history_stream(self, **kwargs):
            self.calls += 1
            if "tools" in kwargs:
                raise RuntimeError("tools unsupported")
            self.fallback_system = kwargs["system"]
            yield (
                '[{"tool":"save_state","args":{}},'
                '{"tool":"create_node","args":{"type":"department","name":"越权部门"}}]'
            )

    client = _FallbackClient()

    async def fail_save_state(ctx_arg):
        dangerous_calls.append("save_state")
        return {"ok": True}

    def fail_create_node(*args, **kwargs):
        dangerous_calls.append("create_node")
        return {"ok": True}

    async def fake_screenshot(ctx_arg):
        return ctx_arg.last_screenshot_url

    monkeypatch.setattr(power_map_service, "_get_llm_client", lambda cfg: client)
    monkeypatch.setattr(power_map_service, "_tool_save_state", fail_save_state)
    monkeypatch.setattr(power_map_service, "_tool_create_node", fail_create_node)

    async def collect_events():
        return [
            event
            async for event in _run_llm_tool_loop(
                ctx=ctx,
                user_text="只调整布局",
                system_prompt="layout-only",
                tools=_layout_execution_tools(),
                cfg=_LoopConfig(),
                screenshot_fn=fake_screenshot,
                max_rounds=1,
                session_id="fallback-session",
                planning_enabled=False,
            )
        ]

    events = asyncio.run(collect_events())
    fallback_section = client.fallback_system.split("【文本工具协议】", 1)[1]
    rejected = [event for event in events if event.type == "tool_result"]

    assert '"save_state"' not in fallback_section
    assert '"create_node"' not in fallback_section
    assert dangerous_calls == []
    assert len(rejected) == 2
    assert all("tool_not_allowed" in str(event.data.get("error")) for event in rejected)


def test_confirm_plan_uses_session_sandbox_and_rejects_zero_rendered_nodes():
    with pytest.raises(RuntimeError, match="sandbox_render_node_mismatch"):
        _validate_sandbox_render_state(
            expected_node_count=36,
            rendered_node_count=0,
            svg_count=4,
        )


def test_confirm_plan_accepts_matching_rendered_nodes():
    _validate_sandbox_render_state(
        expected_node_count=36,
        rendered_node_count=36,
        svg_count=1,
    )


class _FakePage:
    async def set_extra_http_headers(self, headers):
        self.headers = headers

    async def close(self):
        return None


class _FakeContext:
    def __init__(self):
        self.page = _FakePage()

    async def new_page(self):
        return self.page

    async def close(self):
        return None


class _FakeBrowser:
    def __init__(self):
        self.context = _FakeContext()

    async def new_context(self, **kwargs):
        return self.context

    async def close(self):
        return None


class _FakeChromium:
    def __init__(self):
        self.browser = _FakeBrowser()

    async def launch(self, **kwargs):
        return self.browser


class _FakePlaywright:
    def __init__(self):
        self.chromium = _FakeChromium()

    async def stop(self):
        return None


class _FakePlaywrightStarter:
    async def start(self):
        return _FakePlaywright()


def _layout_ctx() -> MergeContext:
    root = PowerNode(id="platform", node_type="dept", name="数据中台", x=100, y=100, w=300, h=200)
    product = PowerNode(
        id="product",
        node_type="dept",
        name="数据产品部",
        parent_dept_id=root.id,
        x=140,
        y=180,
        w=220,
        h=140,
    )
    nodes = [root, product]
    return MergeContext(
        all_nodes=nodes,
        nodes_by_id={node.id: node for node in nodes},
        nodes_by_name={node.name: node for node in nodes},
        depts_by_name={node.name: node for node in nodes},
    )


def test_geometry_checker_uses_actual_department_parent_relationship():
    ctx = _layout_ctx()
    ctx.nodes_by_id["platform"].h = 400

    result = _tool_check_geometry(ctx, list(ctx.nodes_by_id))

    assert result["ok"] is True
    assert result["summary"]["critical"] == 0
    assert result["summary"]["high"] == 0


def test_confirmed_layout_executor_uses_only_layout_tools_and_requires_convergence(monkeypatch):
    ctx = _layout_ctx()
    intent = _parse_power_map_intent(
        '{"goal":"放大数据中台并重新排列","rank_groups":[["数据产品部"]]}'
    )
    screenshot_calls = []
    captured = {}

    async def fake_screenshot(ctx_arg, **kwargs):
        screenshot_calls.append((kwargs["session_id"], kwargs["sandbox_url"]))
        return "data:image/png;base64," + "A" * 512

    async def fake_loop(**kwargs):
        captured["tool_names"] = {
            tool["function"]["name"] for tool in kwargs["tools"]
        }
        captured["planning_enabled"] = kwargs["planning_enabled"]
        ctx.nodes_by_id["platform"].w = 560
        ctx.nodes_by_id["platform"].h = 400
        yield HarnessEvent(type="tool_call", data={"tool": "resize_container", "args": {}})
        yield HarnessEvent(
            type="done",
            data={
                "rounds": 2,
                "executed": 1,
                "converged": True,
                "exit_reason": "natural_converge",
            },
        )

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: _FakePlaywrightStarter())
    monkeypatch.setattr(power_map_service, "_sandbox_screenshot", fake_screenshot)
    monkeypatch.setattr(power_map_service, "_run_llm_tool_loop", fake_loop)

    result = asyncio.run(_execute_confirmed_plan_preview(
        ctx=ctx,
        intent=intent,
        cfg=object(),
        session_id="session-1",
        execute_layout=True,
    ))

    assert result["ok"] is True
    assert result["layout_executed"] is True
    assert result["tool_calls"] == 1
    assert ctx.harness_can_commit is True
    assert captured["planning_enabled"] is False
    assert "resize_container" in captured["tool_names"]
    assert "save_state" not in captured["tool_names"]
    assert screenshot_calls == [
        ("session-1", "http://localhost:8000/sandbox/render?session_id=session-1"),
        ("session-1", "http://localhost:8000/sandbox/render?session_id=session-1"),
    ]


def test_confirmed_layout_executor_blocks_unchanged_geometry(monkeypatch):
    ctx = _layout_ctx()
    intent = _parse_power_map_intent('{"goal":"重新排列"}')

    async def fake_screenshot(ctx_arg, **kwargs):
        return "data:image/png;base64," + "A" * 512

    async def fake_loop(**kwargs):
        yield HarnessEvent(
            type="done",
            data={
                "rounds": 1,
                "executed": 1,
                "converged": True,
                "exit_reason": "natural_converge",
            },
        )

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: _FakePlaywrightStarter())
    monkeypatch.setattr(power_map_service, "_sandbox_screenshot", fake_screenshot)
    monkeypatch.setattr(power_map_service, "_run_llm_tool_loop", fake_loop)

    result = asyncio.run(_execute_confirmed_plan_preview(
        ctx=ctx,
        intent=intent,
        cfg=object(),
        session_id="session-2",
        execute_layout=True,
    ))

    assert result["ok"] is False
    assert result["error"] == "layout_geometry_unchanged"
    assert ctx.harness_can_commit is False


def test_confirmed_layout_executor_blocks_non_convergence(monkeypatch):
    ctx = _layout_ctx()
    intent = _parse_power_map_intent('{"goal":"重新排列"}')

    async def fake_screenshot(ctx_arg, **kwargs):
        return "data:image/png;base64," + "A" * 512

    async def fake_loop(**kwargs):
        ctx.nodes_by_id["platform"].x = 320
        yield HarnessEvent(
            type="done",
            data={
                "rounds": 12,
                "executed": 1,
                "converged": False,
                "exit_reason": "max_rounds",
            },
        )

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: _FakePlaywrightStarter())
    monkeypatch.setattr(power_map_service, "_sandbox_screenshot", fake_screenshot)
    monkeypatch.setattr(power_map_service, "_run_llm_tool_loop", fake_loop)

    result = asyncio.run(_execute_confirmed_plan_preview(
        ctx=ctx,
        intent=intent,
        cfg=object(),
        session_id="session-non-converged",
        execute_layout=True,
    ))

    assert result["ok"] is False
    assert result["error"] == "max_rounds"
    assert ctx.harness_can_commit is False


def test_confirmed_plan_preview_blocks_screenshot_failure(monkeypatch):
    ctx = _layout_ctx()
    intent = _parse_power_map_intent('{"goal":"重新排列"}')

    async def fake_screenshot(ctx_arg, **kwargs):
        raise RuntimeError("sandbox_render_node_mismatch")

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: _FakePlaywrightStarter())
    monkeypatch.setattr(power_map_service, "_sandbox_screenshot", fake_screenshot)

    result = asyncio.run(_execute_confirmed_plan_preview(
        ctx=ctx,
        intent=intent,
        cfg=object(),
        session_id="session-screenshot-failure",
        execute_layout=True,
    ))

    assert result["ok"] is False
    assert "sandbox_render_node_mismatch" in result["error"]
    assert ctx.harness_can_commit is False


@pytest.mark.parametrize(
    ("geometry_report", "expected_error"),
    [
        ({"ok": False, "error": "checker unavailable"}, "confirm_geometry_validation_failed"),
        ({"ok": True, "summary": {"critical": 1, "high": 0}}, "confirm_geometry_blocked"),
    ],
)
def test_confirmed_plan_without_layout_requires_clean_geometry(
    monkeypatch,
    geometry_report,
    expected_error,
):
    ctx = _layout_ctx()
    intent = _parse_power_map_intent('{"goal":"新增联系人"}')

    async def fake_screenshot(ctx_arg, **kwargs):
        return "data:image/png;base64," + "A" * 512

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: _FakePlaywrightStarter())
    monkeypatch.setattr(power_map_service, "_sandbox_screenshot", fake_screenshot)
    monkeypatch.setattr(
        power_map_service,
        "_tool_check_collisions",
        lambda ctx_arg: {"ok": True, "total_collisions": 0},
    )
    monkeypatch.setattr(
        power_map_service,
        "_tool_check_geometry",
        lambda ctx_arg, node_ids: geometry_report,
    )

    result = asyncio.run(_execute_confirmed_plan_preview(
        ctx=ctx,
        intent=intent,
        cfg=object(),
        session_id="session-no-layout-geometry",
        execute_layout=False,
    ))

    assert result["ok"] is False
    assert result["error"] == expected_error
    assert ctx.harness_can_commit is False


def test_confirmed_layout_executor_blocks_geometry_regression(monkeypatch):
    ctx = _layout_ctx()
    intent = _parse_power_map_intent('{"goal":"重新排列"}')
    collision_reports = iter([
        {"ok": True, "total_collisions": 0},
        {"ok": True, "total_collisions": 1},
    ])

    async def fake_screenshot(ctx_arg, **kwargs):
        return "data:image/png;base64," + "A" * 512

    async def fake_loop(**kwargs):
        ctx.nodes_by_id["platform"].x = 320
        yield HarnessEvent(type="tool_call", data={"tool": "move_dept_with_children", "args": {}})
        yield HarnessEvent(
            type="done",
            data={
                "rounds": 2,
                "executed": 1,
                "converged": True,
                "exit_reason": "natural_converge",
            },
        )

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: _FakePlaywrightStarter())
    monkeypatch.setattr(power_map_service, "_sandbox_screenshot", fake_screenshot)
    monkeypatch.setattr(power_map_service, "_run_llm_tool_loop", fake_loop)
    monkeypatch.setattr(power_map_service, "_tool_check_collisions", lambda ctx_arg: next(collision_reports))
    monkeypatch.setattr(
        power_map_service,
        "_tool_check_geometry",
        lambda ctx_arg, node_ids: {"ok": True, "summary": {"critical": 0, "high": 0}},
    )

    result = asyncio.run(_execute_confirmed_plan_preview(
        ctx=ctx,
        intent=intent,
        cfg=object(),
        session_id="session-geometry-failure",
        execute_layout=True,
    ))

    assert result["ok"] is False
    assert result["error"] == "layout_geometry_blocked"
    assert ctx.harness_can_commit is False


@pytest.mark.parametrize(
    ("final_geometry", "expected_error"),
    [
        ({"ok": False, "error": "checker unavailable"}, "layout_geometry_validation_failed"),
        ({"ok": True, "summary": {"critical": 0, "high": 1}}, "layout_geometry_blocked"),
    ],
)
def test_confirmed_layout_executor_requires_successful_clean_geometry(
    monkeypatch,
    final_geometry,
    expected_error,
):
    ctx = _layout_ctx()
    intent = _parse_power_map_intent('{"goal":"重新排列"}')
    geometry_reports = iter([
        {"ok": True, "summary": {"critical": 0, "high": 1}},
        final_geometry,
    ])

    async def fake_screenshot(ctx_arg, **kwargs):
        return "data:image/png;base64," + "A" * 512

    async def fake_loop(**kwargs):
        ctx.nodes_by_id["platform"].x = 320
        yield HarnessEvent(type="tool_call", data={"tool": "move_dept_with_children", "args": {}})
        yield HarnessEvent(
            type="done",
            data={"rounds": 2, "executed": 1, "converged": True, "exit_reason": "natural_converge"},
        )

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: _FakePlaywrightStarter())
    monkeypatch.setattr(power_map_service, "_sandbox_screenshot", fake_screenshot)
    monkeypatch.setattr(power_map_service, "_run_llm_tool_loop", fake_loop)
    monkeypatch.setattr(
        power_map_service,
        "_tool_check_collisions",
        lambda ctx_arg: {"ok": True, "total_collisions": 0},
    )
    monkeypatch.setattr(
        power_map_service,
        "_tool_check_geometry",
        lambda ctx_arg, node_ids: next(geometry_reports),
    )

    result = asyncio.run(_execute_confirmed_plan_preview(
        ctx=ctx,
        intent=intent,
        cfg=object(),
        session_id="session-strict-geometry",
        execute_layout=True,
    ))

    assert result["ok"] is False
    assert result["error"] == expected_error
    assert ctx.harness_can_commit is False


def test_data_platform_layout_command_changes_geometry_without_relayouting_unrequested_edits():
    platform = PowerNode(id="platform", node_type="dept", name="数据中台", x=100, y=100, w=300, h=200)
    product = PowerNode(id="product", node_type="dept", name="数据产品部", parent_dept_id=platform.id, x=140, y=180, w=220, h=140)
    development = PowerNode(id="development", node_type="dept", name="数据开发部", parent_dept_id=platform.id, x=400, y=420, w=220, h=140)
    operations = PowerNode(id="operations", node_type="dept", name="系统运维部", parent_dept_id=platform.id, x=660, y=660, w=220, h=140)
    other = PowerNode(id="other", node_type="dept", name="奇瑞", x=1200, y=200, w=300, h=200)
    other_user = PowerNode(id="other-user", node_type="user", name="业务负责人", parent_dept_id=other.id, x=1250, y=280, w=160, h=72)
    nodes = [platform, product, development, operations, other, other_user]
    ctx = MergeContext(
        all_nodes=nodes,
        nodes_by_id={node.id: node for node in nodes},
        nodes_by_name={node.name: node for node in nodes},
        depts_by_name={node.name: node for node in nodes if node.node_type == "dept"},
    )

    horizontal = _tool_arrange_horizontally(
        ctx,
        [product.id, development.id, operations.id],
        start_x=160,
        y=220,
        gap=40,
    )
    resized = _tool_resize_container(ctx, platform.id, w=900, h=460)
    before_delta = (other_user.x - other.x, other_user.y - other.y)
    vertical = _tool_arrange_vertically(ctx, [other.id], x=120, start_y=720, gap=80)

    assert horizontal["ok"] is True
    assert resized["ok"] is True
    assert vertical["ok"] is True
    assert {product.y, development.y, operations.y} == {220.0}
    assert platform.w == 900
    assert platform.h == 460
    assert (other_user.x - other.x, other_user.y - other.y) == before_delta
    assert other.y == 720.0


def test_data_platform_command_runs_through_llm_layout_dispatcher(monkeypatch):
    platform = PowerNode(id="platform", node_type="dept", name="数据中台", x=100, y=100, w=420, h=260)
    product = PowerNode(id="product", node_type="dept", name="数据产品", parent_dept_id=platform.id, x=140, y=180, w=220, h=140)
    development = PowerNode(id="development", node_type="dept", name="数据开发", parent_dept_id=platform.id, x=420, y=420, w=220, h=140)
    operations = PowerNode(id="operations", node_type="dept", name="系统运维", parent_dept_id=platform.id, x=700, y=660, w=220, h=140)
    other = PowerNode(id="other", node_type="dept", name="其他部门", x=1200, y=200, w=300, h=200)
    nodes = [platform, product, development, operations, other]
    ctx = MergeContext(
        all_nodes=nodes,
        nodes_by_id={node.id: node for node in nodes},
        nodes_by_name={node.name: node for node in nodes},
        depts_by_name={node.name: node for node in nodes},
    )
    intent = _parse_power_map_intent(
        '{"goal":"把数据中台放大、数据产品、数据开发、系统运维放到同一个层级，'
        '把其他的所有部门都单独列成一行进行排列。",'
        '"layout_roots":["数据中台"],'
        '"rank_groups":[["数据产品","数据开发","系统运维"],["其他部门"]]}'
    )

    class _NativeLayoutClient:
        def __init__(self):
            self.calls = 0
            self.first_user_text = ""

        async def messages_create_with_history_stream(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                self.first_user_text = str(kwargs["messages"])
                calls = [
                    ("resize_container", {"container_id": "platform", "w": 1000, "h": 520}),
                    ("arrange_horizontally", {
                        "node_ids": ["product", "development", "operations"],
                        "start_x": 160,
                        "y": 220,
                        "gap": 40,
                    }),
                    ("arrange_vertically", {
                        "node_ids": ["other"],
                        "x": 120,
                        "start_y": 760,
                        "gap": 80,
                    }),
                ]
                for index, (name, args) in enumerate(calls):
                    yield {"type": "tool_call_start", "index": index, "id": f"call-{index}", "name": name}
                    yield {"type": "tool_call_delta", "index": index, "arguments": power_map_service.json.dumps(args)}
                return
            yield {"type": "content", "text": "布局完成"}

    client = _NativeLayoutClient()

    async def fake_screenshot(ctx_arg, **kwargs):
        return "data:image/png;base64," + "A" * 512

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: _FakePlaywrightStarter())
    monkeypatch.setattr(power_map_service, "_get_llm_client", lambda cfg: client)
    monkeypatch.setattr(power_map_service, "_sandbox_screenshot", fake_screenshot)
    monkeypatch.setattr(
        power_map_service,
        "_tool_check_collisions",
        lambda ctx_arg: {"ok": True, "total_collisions": 0},
    )
    monkeypatch.setattr(
        power_map_service,
        "_tool_check_geometry",
        lambda ctx_arg, node_ids: {"ok": True, "summary": {"critical": 0, "high": 0}},
    )

    result = asyncio.run(_execute_confirmed_plan_preview(
        ctx=ctx,
        intent=intent,
        cfg=_LoopConfig(),
        session_id="data-platform-layout",
        execute_layout=True,
    ))

    assert result["ok"] is True
    assert result["layout_executed"] is True
    assert "数据中台" in client.first_user_text
    assert {product.y, development.y, operations.y} == {220.0}
    assert platform.w == 1000
    assert platform.h == 520
    assert other.y == 760.0


class _FakeDb:
    def get(self, model, key):
        return _LoopConfig()


def _draft(plan_id: str, base_ctx: MergeContext) -> PowerMapPlanDraft:
    intent = _parse_power_map_intent('{"goal":"重新排列","rank_groups":[["数据中台"]]}')
    return PowerMapPlanDraft(
        plan_id=plan_id,
        company_id="company-1",
        version=None,
        current_intent=intent,
        plan_text='{"goal":"重新排列"}',
        base_ctx=base_ctx,
        prj_id="project-1",
        version_id="version-1",
    )


def test_confirm_plan_failure_removes_new_failed_session_and_keeps_plan(monkeypatch):
    plan_id = "plan-failure"
    base_ctx = _layout_ctx()
    _store_plan(_draft(plan_id, base_ctx))

    async def fake_preview(**kwargs):
        kwargs["ctx"].all_nodes[0].x = 999
        kwargs["ctx"].harness_can_commit = False
        return {"ok": False, "error": "layout_not_converged"}

    monkeypatch.setattr(power_map_service, "_execute_confirmed_plan_preview", fake_preview)
    try:
        result = asyncio.run(confirm_power_map_plan(
            _FakeDb(),
            "company-1",
            plan_id,
            current_user={"username": "tester"},
        ))

        assert result["ok"] is False
        assert result["error"] == "layout_not_converged"
        assert _get_session(result["session_id"]) is None
        assert _get_plan(plan_id) is not None
        assert base_ctx.all_nodes[0].x == 100
    finally:
        _drop_plan(plan_id)
        if "result" in locals():
            _drop_session(result.get("session_id", ""))


def test_confirm_plan_success_returns_verified_screenshot_and_drops_plan(monkeypatch):
    plan_id = "plan-success"
    base_ctx = _layout_ctx()
    _store_plan(_draft(plan_id, base_ctx))

    async def fake_preview(**kwargs):
        kwargs["ctx"].all_nodes[0].w = 560
        kwargs["ctx"].harness_can_commit = True
        return {
            "ok": True,
            "layout_executed": True,
            "rounds": 2,
            "executed": 3,
            "tool_calls": 3,
            "converged": True,
            "exit_reason": "natural_converge",
            "screenshot_url": "data:image/png;base64," + "A" * 512,
        }

    monkeypatch.setattr(power_map_service, "_execute_confirmed_plan_preview", fake_preview)
    try:
        result = asyncio.run(confirm_power_map_plan(
            _FakeDb(),
            "company-1",
            plan_id,
            current_user={"username": "tester"},
        ))

        assert result["ok"] is True
        assert result["screenshot_url"].startswith("data:image/png;base64,")
        assert result["done"]["layout_executed"] is True
        assert result["done"]["layout_tool_calls"] == 3
        assert _get_plan(plan_id) is None
        stored = _get_session(result["session_id"])
        assert stored is not None
        assert stored.harness_can_commit is True
        assert stored.all_nodes[0].w == 560
    finally:
        _drop_plan(plan_id)
        if "result" in locals():
            _drop_session(result.get("session_id", ""))


def test_confirm_claim_blocks_double_confirm_commit_and_discard(monkeypatch):
    base_session_id = "shared-base-session"
    first_plan_id = "plan-concurrent-first"
    second_plan_id = "plan-concurrent-second"
    base_ctx = _layout_ctx()
    _store_session(base_session_id, base_ctx)
    first_draft = _draft(first_plan_id, base_ctx)
    first_draft.base_session_id = base_session_id
    first_draft.base_ctx = None
    second_draft = _draft(second_plan_id, base_ctx)
    second_draft.base_session_id = base_session_id
    second_draft.base_ctx = None
    _store_plan(first_draft)
    _store_plan(second_draft)
    preview_started = asyncio.Event()
    release_preview = asyncio.Event()

    async def fake_preview(**kwargs):
        preview_started.set()
        await release_preview.wait()
        kwargs["ctx"].all_nodes[0].w = 640
        kwargs["ctx"].harness_can_commit = True
        return {
            "ok": True,
            "layout_executed": True,
            "rounds": 2,
            "executed": 1,
            "tool_calls": 1,
            "converged": True,
            "exit_reason": "natural_converge",
            "screenshot_url": "data:image/png;base64," + "A" * 512,
        }

    monkeypatch.setattr(power_map_service, "_execute_confirmed_plan_preview", fake_preview)

    async def run_interleaving():
        first_task = asyncio.create_task(confirm_power_map_plan(
            _FakeDb(),
            "company-1",
            first_plan_id,
            current_user={"username": "tester"},
        ))
        await preview_started.wait()
        same_plan_result = await confirm_power_map_plan(
            _FakeDb(),
            "company-1",
            first_plan_id,
            current_user={"username": "tester"},
        )
        plan_edit_events = [
            event
            async for event in plan_power_map_v2(
                _FakeDb(),
                "company-1",
                "继续修改计划",
                current_user={"username": "tester"},
                plan_id=first_plan_id,
            )
        ]
        other_plan_result = await confirm_power_map_plan(
            _FakeDb(),
            "company-1",
            second_plan_id,
            current_user={"username": "tester"},
        )
        commit_result = await commit_power_map_session(base_session_id, _FakeDb())
        discard_result = discard_power_map_session(base_session_id)
        release_preview.set()
        first_result = await first_task
        return (
            first_result,
            same_plan_result,
            plan_edit_events,
            other_plan_result,
            commit_result,
            discard_result,
        )

    try:
        first, same_plan, plan_edit_events, other_plan, commit_result, discard_result = asyncio.run(run_interleaving())

        assert first["ok"] is True
        assert first["session_id"] == base_session_id
        assert same_plan == {"ok": False, "error": "plan_busy"}
        assert plan_edit_events[-1].data == {"error": "plan_busy", "phase": "planning"}
        assert other_plan == {"ok": False, "error": "session_busy"}
        assert commit_result == {"ok": False, "error": "session_busy"}
        assert discard_result == {"ok": False, "error": "session_busy"}
        stored = _get_session(base_session_id)
        assert stored is not None
        assert stored.all_nodes[0].w == 640
        assert _get_plan(second_plan_id) is not None
    finally:
        _drop_plan(first_plan_id)
        _drop_plan(second_plan_id)
        _drop_session(base_session_id)


def test_plan_revision_cas_prevents_slow_edit_from_reviving_confirmed_plan(monkeypatch):
    base_session_id = "reverse-race-base-session"
    plan_id = "reverse-race-plan"
    base_ctx = _layout_ctx()
    _store_session(base_session_id, base_ctx)
    draft = _draft(plan_id, base_ctx)
    draft.base_session_id = base_session_id
    draft.base_ctx = None
    _store_plan(draft)
    edit_started = asyncio.Event()
    release_edit = asyncio.Event()

    async def slow_planning(**kwargs):
        edit_started.set()
        await release_edit.wait()
        yield {"type": "done", "plan_text": '{"goal":"重新排列","rank_groups":[["数据中台"]]}'}

    async def fake_preview(**kwargs):
        kwargs["ctx"].all_nodes[0].w = 640
        kwargs["ctx"].harness_can_commit = True
        return {
            "ok": True,
            "layout_executed": True,
            "rounds": 1,
            "executed": 1,
            "tool_calls": 1,
            "converged": True,
            "exit_reason": "natural_converge",
            "screenshot_url": "data:image/png;base64," + "A" * 512,
        }

    monkeypatch.setattr(power_map_service, "_run_kimi_planning_round", slow_planning)
    monkeypatch.setattr(power_map_service, "_execute_confirmed_plan_preview", fake_preview)
    monkeypatch.setattr(power_map_service, "_get_llm_client", lambda cfg: object())

    async def run_interleaving():
        async def collect_edit_events():
            return [
                event
                async for event in plan_power_map_v2(
                    _FakeDb(),
                    "company-1",
                    "继续修改计划",
                    current_user={"username": "tester"},
                    plan_id=plan_id,
                )
            ]

        edit_task = asyncio.create_task(collect_edit_events())
        await edit_started.wait()
        confirm_result = await confirm_power_map_plan(
            _FakeDb(),
            "company-1",
            plan_id,
            current_user={"username": "tester"},
        )
        release_edit.set()
        edit_events = await edit_task
        return confirm_result, edit_events

    try:
        confirm_result, edit_events = asyncio.run(run_interleaving())

        assert confirm_result["ok"] is True
        assert edit_events[-1].data == {"error": "plan_revision_conflict", "phase": "planning"}
        assert _get_plan(plan_id) is None
        stored = _get_session(base_session_id)
        assert stored is not None
        assert stored.all_nodes[0].w == 640
    finally:
        _drop_plan(plan_id)
        _drop_session(base_session_id)


def test_commit_claim_drops_session_after_success(monkeypatch):
    session_id = "commit-success-session"
    ctx = _layout_ctx()
    ctx.harness_cfg = object()
    ctx.harness_prj_id = "project-1"
    ctx.harness_can_commit = True
    _store_session(session_id, ctx)

    async def fake_submit(**kwargs):
        return {"saved": True}

    monkeypatch.setattr(power_map_service, "_submit_to_bi", fake_submit)
    try:
        result = asyncio.run(commit_power_map_session(session_id, _FakeDb()))

        assert result == {"ok": True, "result": {"saved": True}}
        assert _get_session(session_id) is None
    finally:
        _drop_session(session_id)


def test_commit_business_rejection_keeps_session_for_retry(monkeypatch):
    session_id = "commit-business-rejection-session"
    ctx = _layout_ctx()
    ctx.harness_cfg = object()
    ctx.harness_prj_id = "project-1"
    ctx.harness_can_commit = True
    _store_session(session_id, ctx)

    async def fake_submit(**kwargs):
        return {"success": False}

    monkeypatch.setattr(power_map_service, "_submit_to_bi", fake_submit)
    try:
        result = asyncio.run(commit_power_map_session(session_id, _FakeDb()))

        assert result["ok"] is False
        assert "success=false" in result["error"]
        assert _get_session(session_id) is ctx
        assert discard_power_map_session(session_id) == {"ok": True}
    finally:
        _drop_session(session_id)


@pytest.mark.parametrize("failure", [RuntimeError("provider failed"), asyncio.CancelledError()])
def test_commit_claim_is_released_after_submit_failure_or_cancellation(monkeypatch, failure):
    session_id = f"commit-failure-{type(failure).__name__}"
    ctx = _layout_ctx()
    ctx.harness_cfg = object()
    ctx.harness_prj_id = "project-1"
    ctx.harness_can_commit = True
    _store_session(session_id, ctx)

    async def fake_submit(**kwargs):
        raise failure

    monkeypatch.setattr(power_map_service, "_submit_to_bi", fake_submit)
    try:
        if isinstance(failure, asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(commit_power_map_session(session_id, _FakeDb()))
            retry = asyncio.run(commit_power_map_session(session_id, _FakeDb()))
            assert retry == {"ok": False, "error": "commit_outcome_unknown"}
        else:
            result = asyncio.run(commit_power_map_session(session_id, _FakeDb()))
            assert result["ok"] is False
            assert "submit_failed" in result["error"]

        assert discard_power_map_session(session_id) == {"ok": True}
    finally:
        _drop_session(session_id)

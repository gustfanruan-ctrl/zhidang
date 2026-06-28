import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.zhidang_capability_cli import (  # noqa: E402
    _build_merged_record_text,
    _parse_sse_event_lines,
    build_parser,
    build_plan,
)


def _parse(argv):
    return build_parser().parse_args(argv)


def test_followup_generate_builds_text_and_image_request(tmp_path):
    text_file = tmp_path / "meeting.txt"
    text_file.write_text("客户希望下周推进上线。", encoding="utf-8")
    image_file = tmp_path / "shot.png"
    image_file.write_bytes(b"fake-png")

    plan = build_plan(
        _parse([
            "followup",
            "generate",
            "--company-id",
            "company-1",
            "--company-name",
            "测试客户",
            "--text-file",
            str(text_file),
            "--image-file",
            str(image_file),
        ])
    )

    req = plan.requests[0]
    assert plan.capability == "followup"
    assert req["method"] == "POST"
    assert req["path"] == "/api/v1/followup/generate"
    assert req["json"]["input_type"] == "screenshot"
    assert req["json"]["company_id"] == "company-1"
    assert "客户希望下周推进上线" in req["json"]["content"]
    assert req["json"]["images"][0].startswith("data:image/png;base64,")
    assert base64.b64decode(req["json"]["images"][0].split(",", 1)[1]) == b"fake-png"
    assert req["summary"]["image_count"] == 1


def test_expectation_scene_single_transcript_analyzes_existing_record_directly():
    plan = build_plan(
        _parse([
            "expectation-scene",
            "analyze",
            "--transcript-id",
            "transcript-1",
        ])
    )

    assert plan.capability == "expectation_scene"
    assert plan.write_risk == "none"
    assert plan.requests == [
        {
            "method": "POST",
            "path": "/api/v1/transcripts/transcript-1/analyze",
            "content_type": "application/json",
            "params": {},
            "source_record": {"source_type": "transcript", "id": "transcript-1"},
        }
    ]


def test_expectation_scene_followup_record_passes_source_type_followup():
    plan = build_plan(
        _parse([
            "expectation-scene",
            "analyze",
            "--followup-record-id",
            "followup-1",
        ])
    )

    req = plan.requests[0]
    assert req["path"] == "/api/v1/transcripts/followup-1/analyze"
    assert req["params"] == {"source_type": "followup"}
    assert req["source_record"] == {"source_type": "followup", "id": "followup-1"}


def test_expectation_scene_multiple_records_builds_merge_upload_plan():
    plan = build_plan(
        _parse([
            "expectation-scene",
            "analyze",
            "--company-id",
            "company-1",
            "--company-name",
            "测试客户",
            "--transcript-id",
            "t-1",
            "--followup-record-id",
            "f-1",
        ])
    )

    assert [req["method"] for req in plan.requests] == ["GET", "GET", "POST"]
    assert plan.requests[0]["path"] == "/api/v1/transcripts/t-1"
    assert plan.requests[1]["path"] == "/api/v1/followup-records/f-1"
    upload = plan.requests[2]
    assert upload["path"] == "/api/v1/transcript/upload"
    assert upload["form"] == {"company_name_hint": "测试客户", "company_id": "company-1"}
    assert upload["generated_file"]["source_records"] == [
        {"source_type": "transcript", "id": "t-1"},
        {"source_type": "followup", "id": "f-1"},
    ]
    assert "多条已有记录" in " ".join(plan.notes)


def test_build_merged_record_text_preserves_record_source_boundaries():
    merged = _build_merged_record_text([
        {
            "_source_type": "followup",
            "id": "f-1",
            "title": "现场拜访",
            "raw_text": "客户提到希望补充移动端看板。",
        },
        {
            "_source_type": "transcript",
            "id": "t-1",
            "title": "周会转写",
            "raw_text": "业务希望下月完成试点。",
        },
        {
            "_source_type": "transcript",
            "id": "empty",
            "title": "空记录",
            "raw_text": "  ",
        },
    ])

    assert "--- 跟进记录: 现场拜访 ---\n客户提到希望补充移动端看板。" in merged
    assert "--- 会议转写: 周会转写 ---\n业务希望下月完成试点。" in merged
    assert "空记录" not in merged


def test_expectation_scene_upload_files_builds_multipart_plan(tmp_path):
    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.md"
    file_a.write_text("a", encoding="utf-8")
    file_b.write_text("b", encoding="utf-8")

    plan = build_plan(
        _parse([
            "expectation-scene",
            "analyze",
            "--company-id",
            "company-1",
            "--upload-file",
            str(file_a),
            "--upload-file",
            str(file_b),
        ])
    )

    req = plan.requests[0]
    assert req["content_type"] == "multipart/form-data"
    assert req["form"]["company_id"] == "company-1"
    assert [Path(item["path"]).name for item in req["files"]] == ["a.txt", "b.md"]
    assert "多文件上传" in " ".join(plan.notes)


def test_power_map_chat_builds_sse_request_without_commit():
    plan = build_plan(
        _parse([
            "power-map",
            "chat",
            "--company-id",
            "company-1",
            "--version",
            "ver-1",
            "--message",
            "新增一个部门",
        ])
    )

    req = plan.requests[0]
    assert plan.capability == "power_map"
    assert plan.write_risk == "preview_session"
    assert req["path"] == "/api/v1/power-map/company-1/chat_v2"
    assert req["accept"] == "text/event-stream"
    assert req["json"] == {"message": "新增一个部门", "confirm": False, "version": "ver-1"}
    assert any("session_id" in note for note in plan.notes)


def test_power_map_sse_parser_extracts_session_id():
    parsed = _parse_sse_event_lines([
        "event: progress",
        'data: {"message":"正在处理"}',
        "",
        "event: done",
        'data: {"session_id":"session-1","summary":"完成"}',
        "",
    ])

    assert parsed["session_id"] == "session-1"
    assert parsed["events"] == [
        {"event": "progress", "data": {"message": "正在处理"}},
        {"event": "done", "data": {"session_id": "session-1", "summary": "完成"}},
    ]


def test_expectation_scene_requires_some_input():
    try:
        build_plan(_parse(["expectation-scene", "analyze"]))
    except ValueError as exc:
        assert "requires --upload-file" in str(exc)
    else:
        raise AssertionError("expected ValueError")

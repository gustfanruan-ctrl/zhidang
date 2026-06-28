import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = ROOT / "backend" / "app" / "main.py"
TRANSCRIPTS_PAGE = ROOT / "frontend" / "src" / "pages" / "TranscriptsPage.vue"
OPERATION_API = ROOT / "frontend" / "src" / "api" / "operation.js"
FOLLOWUP_RECORDS_API = ROOT / "frontend" / "src" / "api" / "followup-records.js"
CENTALL_AI_TAB = ROOT / ".tmp" / "centall" / "src" / "components" / "features" / "customer" / "AIAssistantTab.tsx"
CENTALL_CHAT_ROUTE = ROOT / ".tmp" / "centall" / "src" / "app" / "api" / "customers" / "[id]" / "chat" / "route.ts"
CENTALL_AGENT_ZHIDANG_TOOL = ROOT / ".tmp" / "centall" / "src" / "lib" / "agent" / "tools" / "zhidang.ts"
CENTALL_AGENT_REGISTRY = ROOT / ".tmp" / "centall" / "src" / "lib" / "agent" / "registry.ts"
CENTALL_ZHIDANG_LANGUAGE = ROOT / ".tmp" / "centall" / "src" / "lib" / "zhidang" / "language.ts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_zhidang_backend_exposes_three_capability_http_contracts():
    source = _read(MAIN_PY)

    assert '@app.post("/api/v1/followup/generate")' in source
    assert '@app.post("/api/v1/followup/submit")' in source
    assert '@app.post("/api/v1/transcript/upload")' in source
    assert '@app.get("/api/v1/transcripts")' in source
    assert '@app.get("/api/v1/followup-records")' in source
    assert '@app.post("/api/v1/transcripts/{transcript_id}/analyze")' in source
    assert '@app.post("/api/v1/operations/execute")' in source
    assert '@app.post("/api/v1/power-map/{company_id}/chat_v2")' in source
    assert '@app.post("/api/v1/power-map/{company_id}/commit")' in source
    assert '@app.post("/api/v1/power-map/{company_id}/discard")' in source


def test_transcript_upload_contract_accepts_multi_file_and_preserves_boundaries():
    source = _read(MAIN_PY)

    signature = re.search(r"async def transcript_upload\((.*?)\):", source, re.S)
    assert signature, "transcript_upload route signature should remain discoverable"
    assert "files: list[UploadFile] = File(...)" in signature.group(1)
    assert "company_name_hint: str = Form" in signature.group(1)
    assert "company_id: str = Form" in signature.group(1)

    assert "if len(files) > 10" in source
    assert "total_size > 16 * 1024 * 1024" in source
    assert '".txt": "text"' in source
    assert '".md": "text"' in source
    assert '".png": "image"' in source
    assert 'merged_text_parts.append(f"--- 文件: {f.filename} ---\\n{content}")' in source
    assert 'merged_text_parts.append(f"--- 文件: {f.filename} (图片) ---")' in source
    assert 'input_type = "mixed"' in source
    assert 'input_type = "image"' in source


def test_frontend_transcripts_page_presents_transcript_and_followup_sources():
    page = _read(TRANSCRIPTS_PAGE)
    operation_api = _read(OPERATION_API)
    followup_api = _read(FOLLOWUP_RECORDS_API)

    assert "sourceMode === 'transcript'" in page
    assert "sourceMode === 'followup'" in page
    assert "转写记录" in page
    assert "跟进记录" in page
    assert "selectedFiles.value.length >= 10" in page
    assert "uploadTranscript(files, companyName, companyId)" in page
    assert "fetchFollowupRecordDetail(id)" in page
    assert "fetchTranscriptDetail(id)" in page
    assert "--- ${label}: ${title} ---\\n${raw}" in page
    assert "startFollowupAnalysis(t.id)" in page
    assert "startTranscriptAnalysis(t.id)" in page
    assert "api.post('/api/v1/transcript/upload'" in operation_api
    assert "api.get('/api/v1/followup-records'" in followup_api
    assert "source_type: 'followup'" in followup_api


def test_operation_execution_and_power_map_commit_remain_explicit_confirmation_steps():
    source = _read(MAIN_PY)
    page = _read(TRANSCRIPTS_PAGE)

    assert "card_ids" in source
    assert "execute_cards(" in source
    assert "JiandaoyunWriter(" in source
    assert "if not session_id:" in source
    assert "commit_power_map_session(session_id, db)" in source
    assert "discard_power_map_session(session_id)" in source
    assert "executeCards(" in page
    assert "card_ids: approved" in page
    assert "field_updates: fieldUpdates" in page
    assert "card_overrides: cardOverrides" in page


def test_centall_ai_assistant_can_present_chat_files_and_controlled_zhidang_tools():
    tab = _read(CENTALL_AI_TAB)
    route = _read(CENTALL_CHAT_ROUTE)
    tool = _read(CENTALL_AGENT_ZHIDANG_TOOL)
    registry = _read(CENTALL_AGENT_REGISTRY)

    assert 'const MAX_FILES = 5' in tab
    assert "const MAX_SIZE = 10" in tab
    assert "hidden multiple accept={ACCEPT}" in tab
    assert "messages: allMessages" in tab
    assert "customerChatStream(ctx, messages)" in route
    assert "for (const f of msg.files.slice(0, 5))" in route
    assert "extractFileText" in route
    assert "image_url" in route

    assert "prepare_zhidang_followup" in tool
    assert "prepare_zhidang_expectation_scene" in tool
    assert "prepare_zhidang_power_map" in tool
    assert "category: 'zhidang'" in tool
    assert "riskLevel: 'read'" in tool
    assert "taint: 'meta'" in tool
    assert "isZhidangCapabilityEnabled()" in registry
    assert "ZHIDANG_TOOLS_ENABLED ? zhidangTools : []" in registry
    assert "operations/execute" not in tool
    assert "commit" not in tool


def test_centall_zhidang_language_contract_covers_records_files_and_confirmation():
    language = _read(CENTALL_ZHIDANG_LANGUAGE)

    assert "上传会议转写或材料文件" in language
    assert "多文件会保留文件边界" in language
    assert "选择已有转写记录" in language
    assert "选择已有跟进记录" in language
    assert "流式方式展示处理进度" in language
    assert "审批后才写入简道云" in language
    assert "确认提交后才写回权力地图" in language

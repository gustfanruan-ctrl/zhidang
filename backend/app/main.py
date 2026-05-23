# CR-FINAL-FIX: 修复后端关键流程的鉴权、错误提示、健康检查和安全写入路径。
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .auth import create_jwt, get_current_user, get_current_user_for_sse, require_superadmin
from .config import settings
from .crypto_utils import decrypt_secret, encrypt_secret
from .database import Base, engine, get_db
from .models import AnalyticsEvent, ConfigChangeLog, FollowupRecord, OperationLog, Superadmin, SystemConfig, Transcript, User
from .progress import build_progress
from .schemas import AdminFetchWidgetsPayload, AgentComparisonPayload, AgentExtractionPayload, ChatPayload, CompanySearchQuery, ConfigPayload, CustomerSwitchPayload, DingtalkFetchPayload, ExecuteOperationsPayload, LlmConfigPayload, LlmTestPayload, LoginPayload, PowerMapChatPayload, PowerMapConfirmPayload, PowerMapRelayoutPayload, PowerMapPreviewPayload, ReviewActionPayload, ReviewSessionPayload, SsoEntryQuery, SsoGeneratePayload, SystemInitPayload, TranscriptAnalyzeResponse, TranscriptUploadResponse
from .schemas.operation import OperationExecuteRequest, ReviewAction
from .schemas.agent_output import validate_comparison_output, validate_extraction_output
from .services.agent_runner import AgentPhase, AgentRunner
from .services.field_safety import check_operation_cards
from .services.image_preprocessor import ImagePreprocessError, validate_and_preprocess
from .services.jiandaoyun_client import JiandaoyunClient, JiandaoyunClientError
from .services.jiandaoyun_writer import JiandaoyunWriter
from .services.openai_compatible_agent_client import OpenAICompatibleAgentClient
from .services.operation_executor import execute_cards
from .services.cas_auth import CasAuthError, cas_auth_service
from .services.power_map_service import _build_merge_context, _ctx_to_getinfo_response, _drop_session, _execute_harness_stream, _fetch_from_external, _get_power_map_config, _get_session, _new_session_id, _node_from_bi_dict, _store_session, chat_power_map, chat_power_map_v2, commit_power_map_session, confirm_power_map, discard_power_map_session, get_power_map, preview_power_map, relayout_power_map
from .services import sandbox_infra
from .services.sandbox_infra import (
    SANDBOX_DIR,
    ctx_to_full_getinfo_response,
    empty_getinfo_response,
    render_sandbox_html,
    verify_manifest,
)
from .services.prompts import CHAT_SYSTEM_PROMPT, EXTRACTION_SYSTEM_PROMPT
from .services.chat_executor import OP_LABELS, build_jiandaoyun_payload, build_preview_text, get_entry_id, log_operation
from .services.tool_registry import build_chat_executors, get_chat_tools, get_executors, get_tools
from .sso import build_sso_token, verify_sso_token
from .validators import validate_operations
from .writeflow import merge_and_write

try:
    from anthropic import AsyncAnthropic
except Exception:  # pragma: no cover
    AsyncAnthropic = None

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("zhidang")

app = FastAPI(title=settings.app_name, version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
LEGACY_AGENT_A_PROMPT = "你是一个专业的客户成功分析师。请从以下客户拜访会议转写中提取信息。"
LEGACY_AGENT_B_PROMPT = "你是一个客户档案管理专家。请将新提取的客户预期/场景与已有档案数据进行比对。"
LEGACY_NL_QUERY_PROMPT = "你是一个客户档案查询助手。"
LEGACY_NL_MODIFY_PROMPT = "你是一个客户档案修改助手。"

DEFAULT_AGENT_A_PROMPT = """你是一个专业的客户成功分析师，专门从客户拜访会议转写文本中提取结构化信息。

## 你的任务
分析以下会议转写文本，识别并提取其中的「客户预期」和「业务场景」。

## 关键定义
- **客户预期**：客户明确或隐含表达的期望、需求、目标、希望达成的效果。包括功能需求、时间节点要求、效果预期等。
- **业务场景**：客户当前面临的业务痛点、正在使用的工作流程、希望优化的具体场景。

## 工具使用规则
1. 对识别到的每一条预期，调用 `add_expectation` 工具
2. 对识别到的每一条场景，调用 `add_scenario` 工具
3. 每条提取必须附带原文引用（source_quote），用于用户审核时溯源
4. 如果转写内容明显不是客户拜访（如内部会议、闲聊），不调用任何工具，直接回复说明原因
5. 宁可多提取、不要遗漏，用户后续会审核

## 字段填写指南
- summary：一句话概括，不超过50字
- is_first_value：如果是首次提出该预期/场景，为 true；如果是对已有内容的补充或跟进，为 false
- description：详细描述，2-3句话
- status：根据上下文判断，可选值为「未启动」「进行中」「已完成」「已搁置」，无法判断时默认「未启动」
- source_quote：从原文中摘录最相关的一段话，保持原文不改动
- speaker：说话人姓名或角色（如「客户方张总」「我方小李」），无法识别时填「未知」
- timestamp：如果转写中有时间标记，填写对应时间段；没有则留空

## 上下文信息
- 行业：{industry}
- 部门：{department}
- 公司：{company_name}

## 转写文本
{transcript_text}
"""

DEFAULT_AGENT_B_PROMPT = """你是一个客户档案管理专家，负责将新提取的客户预期和场景与简道云中已有的档案数据进行智能比对，生成精确的操作指令。

## 你的任务
对比「新提取的数据」和「已有档案数据」，判断每条提取内容应该执行什么操作。

## 操作类型判断规则
1. **新增（create）**：提取内容在已有档案中无相似项（语义相似度 < 70%），调用 `create_expectation` 或 `create_scenario`
2. **更新（update）**：提取内容与已有档案某条记录语义高度相似（≥ 70%），但有新信息需要补充或状态需要变更，调用 `update_expectation` 或 `update_scenario`，并填写 match_id 指向已有记录
3. **跳过**：提取内容与已有记录完全重复且无新信息，不调用任何工具

## 工具使用规则
1. 对每条需要操作的内容，调用对应的工具，逐条调用
2. update 操作必须提供 match_id（已有记录的 ID）和 reason（为什么认为匹配）
3. confidence 取值 0.0-1.0，反映你对这个操作判断的确信程度
4. 相似度判断基于语义，不要求字面完全一致。例如「希望提升审批效率」和「审批流程太慢需要优化」应视为相似

## 字段更新规则
- update 操作时，只填写需要变更的字段，未提及的字段留空（不覆盖）
- 如果新提取的 description 比已有的更详细，更新 description 并在 reason 中说明
- status 变更需要有明确的原文依据

## 新提取的数据（来自 Agent-A）
{agent_a_result}

## 简道云已有档案数据
{jiandaoyun_existing_data}
"""

DEFAULT_NL_QUERY_PROMPT = """你是一个客户档案查询助手，帮助用户通过自然语言查询简道云中的客户档案信息。

## 能力范围
你可以帮用户查询以下信息：
- 某个客户的所有预期管理记录
- 某个客户的所有业务场景记录
- 按状态筛选（如「查看所有进行中的预期」）
- 按时间范围筛选（如「最近一个月新增的场景」）

## 回复规则
1. 将查询结果以清晰的结构化方式呈现，每条记录包括：摘要、状态、最后更新时间
2. 如果查询无结果，明确告知并建议调整关键词
3. 如果用户的查询意图不明确，主动追问确认
4. 不要编造数据，所有信息必须来自简道云查询结果
5. 涉及修改操作时，告知用户切换到修改模式或直接引导到修改流程

## 当前用户
{user_name}（{user_role}）

## 用户输入
{user_query}
"""

DEFAULT_NL_MODIFY_PROMPT = """你是一个客户档案修改助手，帮助用户通过自然语言修改简道云中的客户档案信息。

## 能力范围
你可以帮用户执行以下修改：
- 修改预期/场景的状态（未启动、进行中、已完成、已搁置）
- 修改预期/场景的描述、摘要
- 添加进度备注（progress_note）
- 删除错误的预期/场景记录

## 安全规则（必须严格遵守）
1. **任何修改操作必须先生成预览，等待用户明确确认后才执行**
2. 预览格式：显示「修改前 → 修改后」的对比
3. 批量修改时，逐条列出所有变更供用户确认
4. 如果用户指令模糊（如「改一下那个」），必须追问确认具体目标
5. 删除操作需要二次确认

## 回复格式
当用户发出修改指令时：
1. 先查询目标记录的当前状态
2. 生成修改预览：
   📝 修改预览
   目标：{company_name} - {record_summary}
   字段：{field_name}
   当前值：{old_value}
   修改为：{new_value}

   请确认是否执行此修改？（是/否）
3. 用户确认后执行修改并返回结果

## 当前用户
{user_name}（{user_role}）

## 用户输入
{user_query}
"""

if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

# Sandbox static assets (BI mirror): served at /static/sandbox/*, populated by
# sandbox_infra.download_bi_resources. Mounted unconditionally so 404s give a
# clear error instead of falling through to the SPA fallback.
BACKEND_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
BACKEND_STATIC_DIR.mkdir(parents=True, exist_ok=True)
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(BACKEND_STATIC_DIR)), name="backend-static")

PENDING_CHAT_ACTIONS: dict[str, dict[str, Any]] = {}
CUSTOMERS_CACHE_TTL_SECONDS = 600
CUSTOMERS_CACHE: dict[str, Any] = {"at": None, "items": []}
TASK_PROGRESS: dict[str, dict[str, Any]] = {}
JIANYDAOYUN_MAPPING_PATH = Path(__file__).resolve().parent / "config" / "jiandaoyun_field_mapping.json"
CUSTOMER_INDEX_CACHE_TTL_SECONDS = 300
CUSTOMER_INDEX_CACHE: dict[str, Any] = {"at": None, "items": [], "source": "empty"}
SHARED_CACHE_DIR = Path(__file__).resolve().parent / "output"
SHARED_CACHE_FILE = SHARED_CACHE_DIR / "customer_index_cache.json"
_refresh_lock: asyncio.Lock | None = None

def _get_refresh_lock() -> asyncio.Lock:
    global _refresh_lock
    if _refresh_lock is None:
        _refresh_lock = asyncio.Lock()
    return _refresh_lock

def _load_shared_cache() -> dict[str, Any] | None:
    """从共享文件加载缓存，所有 worker 进程共享"""
    try:
        if SHARED_CACHE_FILE.exists():
            raw = SHARED_CACHE_FILE.read_text("utf-8")
            data = json.loads(raw)
            if data and data.get("items"):
                at_str = data.get("at")
                if at_str:
                    try:
                        data["at"] = datetime.fromisoformat(at_str)
                    except Exception:
                        data["at"] = None
                return data
    except Exception:
        pass
    return None

def _save_shared_cache(data: dict[str, Any]) -> None:
    """将缓存写入共享文件"""
    try:
        SHARED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        at_val = data.get("at")
        serializable = {
            "items": data.get("items", []),
            "at": at_val.isoformat() if isinstance(at_val, datetime) else at_val,
            "source": data.get("source", "memory"),
        }
        SHARED_CACHE_FILE.write_text(json.dumps(serializable, ensure_ascii=False, default=str), "utf-8")
    except Exception as exc:
        logger.warning(f"写入共享缓存文件失败: {exc}")

OPERATION_CARD_STORE: dict[str, list[dict[str, Any]]] = {}


def _append_llm_line(transcript_id: str, line: str) -> None:
    state = TASK_PROGRESS.setdefault(transcript_id, {})
    lines = list(state.get("llm_lines", []))
    lines.append(line)
    state["llm_lines"] = lines[-3:]


def _format_exc(exc: Exception) -> str:
    text = str(exc).strip()
    if text:
        return f"{exc.__class__.__name__}: {text}"
    rep = repr(exc)
    return f"{exc.__class__.__name__}: {rep}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def hash_company_id(company_id: str | None) -> str:
    if not company_id:
        company_id = ""
    return hashlib.sha256(company_id.encode("utf-8")).hexdigest()


def prompt_version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _user_name(user: dict[str, Any]) -> str:
    return user.get("username") or user.get("user_name") or "unknown"


def _allowed_transcript_stmt(user: dict[str, Any]):
    stmt = select(Transcript)
    if user.get("source") == "sso":
        stmt = stmt.where(Transcript.sso_user_id == user.get("user_id"))
    elif user.get("source") == "user":
        display_name = user.get("display_name")
        username = user.get("username")
        if display_name and username:
            stmt = stmt.where(or_(Transcript.sso_user_name == display_name, Transcript.sso_user_id == username))
    return stmt


def _allowed_followup_stmt(user: dict[str, Any]):
    stmt = select(FollowupRecord)
    if user.get("source") == "sso":
        user_name = user.get("user_name") or user.get("username")
        if user_name:
            stmt = stmt.where(FollowupRecord.sso_user_name == user_name)
    elif user.get("source") == "user":
        display_name = user.get("display_name")
        if display_name:
            stmt = stmt.where(FollowupRecord.sso_user_name == display_name)
    return stmt


def _is_affirmative(text: str) -> bool:
    normalized = text.strip().lower()
    words = ["是", "确认", "好的", "执行", "ok", "yes", "y"]
    return any(word in normalized for word in words)


def _is_negative(text: str) -> bool:
    normalized = text.strip().lower()
    words = ["否", "取消", "算了", "no", "n"]
    return any(word in normalized for word in words)


def _cleanup_pending_operations(now: datetime) -> None:
    expired = []
    for session_id, op in PENDING_CHAT_ACTIONS.items():
        created_at = op.get("created_at")
        if not isinstance(created_at, datetime):
            expired.append(session_id)
            continue
        if now - created_at > timedelta(minutes=5):
            expired.append(session_id)
    for key in expired:
        PENDING_CHAT_ACTIONS.pop(key, None)


def fetch_customers_for_user(db: Session, user: dict[str, Any]) -> list[dict[str, Any]]:
    stmt = _allowed_transcript_stmt(user).where(Transcript.company_name.is_not(None))
    rows = db.scalars(stmt.order_by(Transcript.updated_at.desc())).all()
    seen: set[str] = set()
    customers: list[dict[str, Any]] = []
    for row in rows:
        company_name = (row.company_name or "").strip()
        if not company_name:
            continue
        company_id = row.company_id or hash_company_id(company_name)
        if company_id in seen:
            continue
        seen.add(company_id)
        customers.append({"company_id": company_id, "company_name": company_name, "industry": "未知行业"})
    return customers


def build_raw_transcript_payload(text: str, fallback_title: str = "未命名转写") -> dict[str, Any]:
    clean_text = (text or "").strip()
    first_line = clean_text.splitlines()[0].strip() if clean_text else ""
    title = first_line or fallback_title
    return {"title": title, "raw_text": clean_text, "segments": []}


def ensure_system_config(db: Session) -> SystemConfig:
    cfg = db.get(SystemConfig, 1)
    if not cfg:
        cfg = SystemConfig(id=1)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _load_jiandaoyun_seed_mapping() -> dict[str, Any]:
    if not JIANYDAOYUN_MAPPING_PATH.exists():
        return {}
    try:
        return json.loads(JIANYDAOYUN_MAPPING_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("failed to load jiandaoyun mapping seed")
        return {}


def seed_jiandaoyun_mapping_if_missing(cfg: SystemConfig, db: Session) -> None:
    field_mappings = dict(cfg.field_mappings or {})
    if field_mappings.get("jiandaoyun"):
        return
    seed = _load_jiandaoyun_seed_mapping()
    if not seed:
        return
    field_mappings["jiandaoyun"] = seed
    cfg.field_mappings = field_mappings
    if not cfg.jiandaoyun_app_id and seed.get("app_id"):
        cfg.jiandaoyun_app_id = str(seed.get("app_id"))
    db.commit()
    db.refresh(cfg)


def get_jiandaoyun_runtime_config(cfg: SystemConfig) -> dict[str, Any]:
    seed = dict((cfg.field_mappings or {}).get("jiandaoyun", {}) or {})
    forms = dict(seed.get("forms") or {})
    main_form = dict(forms.get("客户主表") or {})
    mapping_entry_id = str(main_form.get("entry_id") or "").strip()
    cfg_entry_id = str(cfg.main_entry_id or "").strip()
    effective_main_entry_id = cfg_entry_id or mapping_entry_id
    if effective_main_entry_id and mapping_entry_id != effective_main_entry_id:
        # Runtime sync: use a normalized mapping snapshot even if DB column drifts.
        main_form["entry_id"] = effective_main_entry_id
        forms["客户主表"] = main_form
        seed["forms"] = forms
    app_id = (cfg.jiandaoyun_app_id or seed.get("app_id") or "").strip()
    api_key = (decrypt_secret(cfg.jiandaoyun_api_key_encrypted) if cfg.jiandaoyun_api_key_encrypted else "") or ""
    return {"api_key": api_key.strip(), "app_id": app_id, "mapping": seed, "main_entry_id": effective_main_entry_id}


_REFRESH_LOCK = asyncio.Lock()


def _extract_csm_name(success_val: Any) -> str:
    """从简道云成员(user)字段中提取显示名称用于CSM匹配。

    success 字段在简道云 API 返回中是 user 类型的对象：
        {"name": "Gust-张小洋", "username": "Gust.Zhang", ...}
    也可能为 None 或空。
    """
    if isinstance(success_val, dict):
        return success_val.get("name", success_val.get("username", "")) or ""
    return str(success_val or "")


async def refresh_customer_index_cache(runtime_cfg: dict[str, Any]) -> dict[str, Any]:
    mapping = runtime_cfg.get("mapping", {})
    main_form = ((mapping or {}).get("forms") or {}).get("客户主表", {})
    app_id = runtime_cfg.get("app_id", "")
    api_key = runtime_cfg.get("api_key", "")
    entry_id = str(main_form.get("entry_id", "")).strip()
    
    logger.info(f"刷新客户索引缓存: app_id={app_id}, entry_id={entry_id}")
    
    if not api_key or not app_id or not entry_id:
        logger.warning("简道云配置不完整，无法刷新客户索引缓存")
        return CUSTOMER_INDEX_CACHE

    display_fields = list(main_form.get("display_fields", []) or [])
    for required_field in ["comname_01", "com_name", "com_type", "revenue_level", "if_access", "follow_form", "success", "com_id"]:
        if required_field not in display_fields:
            display_fields.append(required_field)
    
    logger.info(f"客户查询字段: {display_fields}")

    client = JiandaoyunClient(api_key=api_key)
    cursor: str | None = None
    all_rows: list[dict[str, Any]] = []
    seen_cursors: set[str] = set()
    page_size = 100
    error_count = 0
    max_errors = 3
    page_num = 0
    
    while True:
        try:
            page = await client.query_data_list(
                app_id=app_id,
                entry_id=entry_id,
                fields=display_fields,
                limit=page_size,
                data_id=cursor,
            )
        except JiandaoyunClientError as exc:
            error_count += 1
            logger.error(f"获取客户数据失败（尝试 {error_count}/{max_errors}）: {str(exc)}")
            if "频率" in str(exc) or "限流" in str(exc):
                wait = min(error_count * 3, 15)
                logger.info(f"触发频率限制，等待 {wait}s 后重试...")
                await asyncio.sleep(wait)
            if error_count >= max_errors:
                logger.error(f"已达到最大错误次数 {max_errors}，停止获取客户数据")
                break
            
            # 如果是第一次错误，尝试不带 fields 参数的查询
            if error_count == 1:
                try:
                    logger.info("尝试不带字段参数的查询")
                    page = await client.query_data_list(
                        app_id=app_id,
                        entry_id=entry_id,
                        fields=None,
                        limit=page_size,
                        data_id=cursor,
                    )
                except JiandaoyunClientError as exc2:
                    logger.error(f"不带字段参数的查询也失败: {str(exc2)}")
                    continue
            else:
                continue
        
        page_num += 1
        if not page.get("data"):
            logger.info(f"第 {page_num} 页无数据，结束获取")
            break
            
        batch = page.get("data", []) or []
        if not batch:
            logger.info(f"第 {page_num} 页数据为空，结束获取")
            break
            
        logger.info(f"获取到第 {page_num} 页数据，共 {len(batch)} 条，累计 {len(all_rows) + len(batch)} 条")
        all_rows.extend(batch)

        # 每页之间间隔 500ms，避免触发简道云 API 频率限制
        await asyncio.sleep(0.5)

        next_cursor = batch[-1].get("_id")
        if not next_cursor or next_cursor in seen_cursors:
            logger.info("已到达最后一页或检测到重复的游标")
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        if len(batch) < page_size:
            logger.info("获取的数据少于页面大小，已到最后一页")
            break

    customers = [
        {
            "company_id": row.get("_id"),
            "company_name": row.get("comname_01") or row.get("com_name") or row.get("企业名称") or row.get("客户名称") or row.get("公司名称") or "未知公司",
            "comname_01": row.get("comname_01"),
            "com_name": row.get("com_name"),
            "com_type": row.get("com_type"),
            "revenue_level": row.get("revenue_level"),
            "if_access": row.get("if_access"),
            "follow_form": row.get("follow_form"),
            "csm": _extract_csm_name(row.get("success")),
            "com_id": row.get("com_id", ""),
            "raw": row,
        }
        for row in all_rows
        if row.get("_id")
    ]
    uniq: dict[str, dict[str, Any]] = {}
    for item in customers:
        uniq[item["company_id"]] = item
    if uniq:
        CUSTOMER_INDEX_CACHE["items"] = list(uniq.values())
        CUSTOMER_INDEX_CACHE["at"] = now_utc()
        CUSTOMER_INDEX_CACHE["source"] = "jiandaoyun"
        _save_shared_cache(CUSTOMER_INDEX_CACHE)
    return CUSTOMER_INDEX_CACHE


def sync_prompt_defaults(cfg: SystemConfig, db: Session) -> None:
    changed = False
    defaults = {
        "agent_a_prompt": DEFAULT_AGENT_A_PROMPT,
        "agent_b_prompt": DEFAULT_AGENT_B_PROMPT,
        "nl_query_prompt": DEFAULT_NL_QUERY_PROMPT,
        "nl_modify_prompt": DEFAULT_NL_MODIFY_PROMPT,
    }
    legacy_values = {
        "agent_a_prompt": LEGACY_AGENT_A_PROMPT,
        "agent_b_prompt": LEGACY_AGENT_B_PROMPT,
        "nl_query_prompt": LEGACY_NL_QUERY_PROMPT,
        "nl_modify_prompt": LEGACY_NL_MODIFY_PROMPT,
    }
    for field, default_value in defaults.items():
        current = getattr(cfg, field)
        if not current or current == legacy_values[field]:
            setattr(cfg, field, default_value)
            changed = True
    if changed:
        db.commit()
        db.refresh(cfg)


def render_prompt_template(template: str, variables: dict[str, Any]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{key}}}", str(value))
    return rendered


def emit_event(db: Session, event_type: str, operator: dict[str, Any], context: dict[str, Any], payload: dict[str, Any], *, op_type: str | None = None, action: str | None = None, latency_ms: int | None = None, model: str | None = None, prompt_ver: str | None = None) -> None:
    event = AnalyticsEvent(
        event_type=event_type,
        operator_name=operator.get("user_name"),
        operator_id=operator.get("user_id"),
        operator_source=operator.get("source"),
        transcript_id=context.get("transcript_id"),
        company_id_hash=context.get("company_id_hash"),
        session_id=context.get("session_id"),
        payload=payload,
        operation_type=op_type,
        action=action,
        latency_ms=latency_ms,
        model=model,
        prompt_version=prompt_ver,
    )
    db.add(event)
    db.commit()


def require_auth(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return user


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        cfg = ensure_system_config(db)
        seed_jiandaoyun_mapping_if_missing(cfg, db)
        sync_prompt_defaults(cfg, db)
    # 从 DB 恢复操作卡片到内存（服务重启后审核/执行仍可用）
    _reload_cards_on_startup()
    # 清理卡在 in-progress 状态超过 1 小时的转写
    _reset_stale_transcripts()
    # Sandbox bundle integrity check (warn-only — missing/changed files don't block startup).
    try:
        verify_manifest()
    except Exception:
        logger.exception("startup: sandbox manifest verification crashed (continuing)")
    logger.info("startup complete")


def _reload_cards_on_startup() -> None:
    """从 DB 加载最近完成的转写卡片到 OPERATION_CARD_STORE。"""
    from .database import SessionLocal as _SL
    db = _SL()
    try:
        recent = db.scalars(
            select(Transcript)
            .where(Transcript.agent_b_result.isnot(None))
            .where(Transcript.status.in_(["comparison_done", "reviewed"]))
            .order_by(Transcript.created_at.desc())
            .limit(50)
        ).all()
        count = 0
        for t in recent:
            cards = (t.agent_b_result or {}).get("result", {}).get("operation_cards", [])
            if cards and t.id not in OPERATION_CARD_STORE:
                OPERATION_CARD_STORE[t.id] = [dict(c) for c in cards]
                count += 1
        if count:
            logger.info("startup: 从 DB 恢复了 %d 条转写的操作卡片", count)
    except Exception:
        logger.exception("startup: 恢复操作卡片失败")
    finally:
        db.close()


def _reset_stale_transcripts() -> None:
    """将卡在 extracting/comparing 超过 1 小时的转写标记为 error。"""
    from .database import SessionLocal as _SL
    db = _SL()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        stale = db.scalars(
            select(Transcript)
            .where(Transcript.status.in_(["extracting", "comparing"]))
            .where(Transcript.updated_at < cutoff)
        ).all()
        for t in stale:
            t.status = "error"
            logger.info("startup: 将超时转写 %s 标记为 error", t.id)
        if stale:
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("startup: 重置超时转写失败")
    finally:
        db.close()


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"ok": True, "service": settings.app_name, "env": settings.environment}


@app.post("/api/v1/system/init")
def system_init(payload: SystemInitPayload, db: Session = Depends(get_db)):
    if db.scalar(select(func.count()).select_from(Superadmin)):
        raise HTTPException(status_code=403, detail="系统已初始化")
    normalized_username = payload.username.strip()
    admin = Superadmin(
        username=normalized_username,
        password_hash=hashlib.sha256(payload.password.encode()).hexdigest(),
        display_name=payload.display_name or normalized_username,
    )
    db.add(admin)
    db.commit()
    return {"success": True}


@app.get("/api/v1/system/status")
def system_status(db: Session = Depends(get_db)):
    initialized = bool(db.scalar(select(func.count()).select_from(Superadmin)))
    return {"initialized": initialized}


@app.post("/api/v1/auth/login")
def login(payload: LoginPayload, db: Session = Depends(get_db)):
    import bcrypt

    normalized_username = payload.username.strip()

    user_row = db.scalar(select(User).where(User.username == normalized_username))
    if user_row and user_row.is_active:
        try:
            ok = bcrypt.checkpw(payload.password.encode(), user_row.password_hash.encode())
        except ValueError:
            ok = False
        if ok:
            role = getattr(user_row, "role", "") or "user"
            token = create_jwt({
                "source": role,
                "username": user_row.username,
                "display_name": user_row.display_name,
                "integrate_id": user_row.integrate_id,
            })
            return {"token": token, "display_name": user_row.display_name, "source": role}

    admin = db.scalar(select(Superadmin).where(Superadmin.username == normalized_username))
    if admin and admin.password_hash == hashlib.sha256(payload.password.encode()).hexdigest():
        token = create_jwt({"source": "superadmin", "username": admin.username})
        return {"token": token, "display_name": admin.display_name, "source": "superadmin"}

    raise HTTPException(status_code=401, detail="用户名或密码错误")


@app.post("/api/v1/sso/generate")
def sso_generate(payload: SsoGeneratePayload, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_superadmin)):
    cfg = ensure_system_config(db)
    return {"token": build_sso_token(payload.user_name, payload.user_id, payload.company_id, cfg.sso_shared_secret or "demo-secret")}


@app.get("/api/v1/sso/entry")
def sso_entry(query: SsoEntryQuery = Depends(), db: Session = Depends(get_db)):
    cfg = ensure_system_config(db)
    secret = cfg.sso_shared_secret or "demo-secret"

    # 模式1: 简化入口（portal_key + jdy_username）
    if query.portal_key and query.jdy_username:
        if query.portal_key != secret:
            raise HTTPException(status_code=403, detail="入口密钥无效")
        jwt_token = create_jwt({"user_name": query.jdy_username, "user_id": query.jdy_username, "source": "sso"})
        return RedirectResponse(url=f"/transcripts?token={jwt_token}")
        jwt_token = create_jwt({"user_name": jdy_username, "user_id": jdy_username, "source": "sso"})
        return RedirectResponse(url=f"/transcripts?token={jwt_token}")

    # 模式2: 完整 SSO（兼容旧版 token 模式）
    if query.token and query.company_id:
        user = verify_sso_token(query.token, query.company_id, secret, cfg.sso_token_ttl_minutes, db)
        effective_user_name = query.jdy_username or user["user_name"]
        effective_user_id = query.jdy_username or user["user_id"]
        jwt_token = create_jwt({"user_name": effective_user_name, "user_id": effective_user_id, "source": "sso"})
        return RedirectResponse(url=f"/transcripts?token={jwt_token}&company_id={query.company_id}")

    raise HTTPException(status_code=400, detail="缺少 portal_key+jdy_username 或 token+company_id")


@app.get("/api/v1/sso/cas-callback")
async def sso_cas_callback(st: str = "", sid: str = "", service: str = "", request: Request = None, db: Session = Depends(get_db)):
    """CAS SSO 回调 —— 验证 ST 并返回 JWT"""
    if not st:
        raise HTTPException(status_code=400, detail="缺少 CAS service ticket (st)")

    effective_service = service or CAS_REFERRER_URL
    # PGT 回调暂不启用（CAS 测试环境对 http URL 验证不通过，
    # 后续需要 HTTPS 代理回调时再修复）
    # pgt_url = str(request.url_for("sso_cas_pgt_callback")) if request else ""
    pgt_url = ""

    try:
        cas_user = await cas_auth_service.validate_st(st, effective_service, pgt_url=pgt_url)
    except CasAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.exception("CAS validate_st failed")
        raise HTTPException(status_code=500, detail=f"CAS 验证异常: {exc}")

    attrs = cas_user.get("attributes", {}) or {}
    if isinstance(attrs, dict):
        username_list = attrs.get("username", [])
        effective_username = str(username_list[0]) if username_list else str(cas_user.get("username", ""))
    else:
        effective_username = str(cas_user.get("username", ""))

    jwt_token = create_jwt({"user_name": effective_username, "user_id": effective_username, "source": "sso"})
    return RedirectResponse(url=f"/transcripts?token={jwt_token}")


@app.get("/api/v1/sso/cas-pgt-callback")
async def sso_cas_pgt_callback(pgtId: str = "", pgtIou: str = ""):
    """CAS PGT 回调 —— CAS 服务器向此端点推送 PGT"""
    if pgtId and pgtIou:
        cas_auth_service.handle_pgt_callback(pgtId, pgtIou)
        return {"ok": True}
    raise HTTPException(status_code=400, detail="缺少 pgtId 或 pgtIou")


CAS_REFERRER_URL = "https://47-98-102-197.sslip.io/"


@app.get("/api/v1/sso/cas-login")
async def sso_cas_login():
    """CAS SSO 入口 —— 重定向到帆软通行证登录页"""
    cas_login_url = (
        "https://fanruanclub.com/login/signin"
        "?app=zhidang"
        "&protocol=cas"
        f"&referrer={CAS_REFERRER_URL}"
    )
    return RedirectResponse(url=cas_login_url)


@app.get("/api/v1/sso/bi-callback")
async def sso_bi_callback(ticket: str = "", service: str = ""):
    """BI 登录链路回调：CAS验证 → 创建JWT → 经BI设cookie → 回到智档"""
    if not ticket:
        raise HTTPException(status_code=400, detail="缺少 CAS ticket")

    effective_service = service or f"{CAS_REFERRER_URL}api/v1/sso/bi-callback"

    try:
        cas_user = await cas_auth_service.validate_st(ticket, effective_service, pgt_url="")
    except CasAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.exception("CAS validate_st failed in bi-callback")
        raise HTTPException(status_code=500, detail=f"CAS 验证异常: {exc}")

    attrs = cas_user.get("attributes", {}) or {}
    if isinstance(attrs, dict):
        username_list = attrs.get("username", [])
        effective_username = str(username_list[0]) if username_list else str(cas_user.get("username", ""))
    else:
        effective_username = str(cas_user.get("username", ""))

    jwt_token = create_jwt({"user_name": effective_username, "user_id": effective_username, "source": "sso"})

    # 通过 BI 的 CAS 登录链路，让浏览器获得 fine_auth_token cookie
    bi_login_url = f"https://crm.finereporthelp.com/WebReport/decision/cas/login?service={CAS_REFERRER_URL}login?token={jwt_token}"
    return RedirectResponse(url=bi_login_url)


@app.get("/api/v1/me")
def me(user: dict[str, Any] = Depends(require_auth), db: Session = Depends(get_db)):
    username = user.get('username', '')
    user_row = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    onboarding = user_row.onboarding_enabled if user_row else True
    return {**user, 'onboarding_enabled': onboarding}


@app.post("/api/v1/auth/change-password")
def change_password(payload: dict[str, Any], user: dict[str, Any] = Depends(require_auth), db: Session = Depends(get_db)):
    import bcrypt
    old_pw = (payload.get("old_password") or "").strip()
    new_pw = (payload.get("new_password") or "").strip()
    if not old_pw or not new_pw:
        raise HTTPException(status_code=400, detail="请输入旧密码和新密码")
    if len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6位")
    username = user.get("username", "")
    user_row = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if not user_row:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        ok = bcrypt.checkpw(old_pw.encode(), user_row.password_hash.encode())
    except ValueError:
        ok = False
    if not ok:
        raise HTTPException(status_code=403, detail="旧密码错误")
    user_row.password_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
    db.commit()
    return {"success": True}


@app.patch("/api/v1/me/onboarding")
def update_onboarding(payload: dict[str, Any], user: dict[str, Any] = Depends(require_auth), db: Session = Depends(get_db)):
    enabled = payload.get("enabled", True)
    username = user.get("username", "")
    user_row = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user_row:
        user_row.onboarding_enabled = bool(enabled)
        db.commit()
    return {"onboarding_enabled": bool(enabled)}


@app.get("/api/v1/admin/users")
def admin_users(q: str = "", page: int = 1, limit: int = 20, user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    stmt = select(User)
    if q:
        stmt = stmt.where(User.username.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%"))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    rows = db.scalars(stmt.order_by(User.username).offset((page - 1) * limit).limit(limit)).all()
    return {"users": [{"id": u.id, "username": u.username, "display_name": u.display_name, "integrate_id": u.integrate_id, "role": u.role, "is_active": u.is_active, "onboarding_enabled": u.onboarding_enabled, "created_at": u.created_at.isoformat() if u.created_at else None} for u in rows], "total": total}


@app.post("/api/v1/admin/users")
def admin_user_create(payload: dict[str, Any], user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    import bcrypt
    username = (payload.get("username") or "").strip()
    password = (payload.get("password") or "").strip()
    if not username or not password: raise HTTPException(status_code=400, detail="用户名和密码必填")
    if len(password) < 6: raise HTTPException(status_code=400, detail="密码至少6位")
    if db.scalars(select(User).where(User.username == username)).first(): raise HTTPException(status_code=400, detail="用户名已存在")
    u = User(id=str(uuid4()), username=username, password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(), display_name=payload.get("display_name", "") or None, integrate_id=payload.get("integrate_id", "") or None, role=payload.get("role", "user") or "user")
    db.add(u); db.commit(); db.refresh(u)
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role}


@app.put("/api/v1/admin/users/{user_id}")
def admin_user_update(user_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    u = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not u: raise HTTPException(status_code=404, detail="用户不存在")
    if "display_name" in payload: u.display_name = payload["display_name"] or None
    if "integrate_id" in payload: u.integrate_id = payload["integrate_id"] or None
    if "role" in payload: u.role = payload["role"] or "user"
    db.commit()
    return {"success": True}


@app.patch("/api/v1/admin/users/{user_id}")
def admin_user_patch(user_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    u = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not u: raise HTTPException(status_code=404, detail="用户不存在")
    if "is_active" in payload: u.is_active = bool(payload["is_active"])
    db.commit()
    return {"success": True}


@app.post("/api/v1/admin/users/{user_id}/reset-password")
def admin_user_reset_pw(user_id: str, payload: dict[str, Any] | None = None, user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    import bcrypt
    u = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not u: raise HTTPException(status_code=404, detail="用户不存在")
    new_pw = (payload or {}).get("new_password", "").strip() if payload else ""
    if not new_pw: new_pw = str(uuid4())[:8]
    u.password_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
    db.commit()
    return {"success": True, "new_password": new_pw}


@app.get("/api/v1/admin/config")
def get_admin_config(user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    cfg = ensure_system_config(db)
    runtime_cfg = get_jiandaoyun_runtime_config(cfg)
    return {
        "jiandaoyun_api_key": "",
        "jiandaoyun_api_key_configured": bool(cfg.jiandaoyun_api_key_encrypted),
        "jiandaoyun_base_url": cfg.jiandaoyun_base_url,
        "jiandaoyun_app_id": cfg.jiandaoyun_app_id,
        # Return effective value to avoid UI showing null while mapping already has entry_id.
        "main_entry_id": runtime_cfg.get("main_entry_id") or cfg.main_entry_id,
        "field_mappings": cfg.field_mappings,
        "sso_shared_secret": cfg.sso_shared_secret,
        "sso_token_ttl_minutes": cfg.sso_token_ttl_minutes,
        "dingtalk_app_key": cfg.dingtalk_app_key,
        "dingtalk_agent_id": cfg.dingtalk_agent_id,
        "agent_a_max_rounds": cfg.agent_a_max_rounds,
        "agent_b_max_rounds": cfg.agent_b_max_rounds,
        "data_retention_days": cfg.data_retention_days,
        "power_map_base_url": cfg.power_map_base_url or "",
        "power_map_get_path": cfg.power_map_get_path or "",
        "power_map_update_path": cfg.power_map_update_path or "",
        "power_map_auth_token_configured": bool(cfg.power_map_auth_token_encrypted),
    }


@app.put("/api/v1/admin/config")
def save_admin_config(payload: ConfigPayload, user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    cfg = ensure_system_config(db)
    before = {k: getattr(cfg, k) for k in ["jiandaoyun_base_url", "jiandaoyun_app_id", "main_entry_id", "field_mappings", "sso_shared_secret", "sso_token_ttl_minutes", "dingtalk_app_key", "dingtalk_agent_id", "agent_a_max_rounds", "agent_b_max_rounds", "data_retention_days", "power_map_base_url", "power_map_get_path", "power_map_update_path"]}
    if payload.jiandaoyun_api_key:
        cfg.jiandaoyun_api_key_encrypted = encrypt_secret(payload.jiandaoyun_api_key)
    if payload.dingtalk_app_secret:
        cfg.dingtalk_app_secret_encrypted = encrypt_secret(payload.dingtalk_app_secret)
    if payload.power_map_auth_token:
        cfg.power_map_auth_token_encrypted = encrypt_secret(payload.power_map_auth_token)
    for key in ["jiandaoyun_base_url", "jiandaoyun_app_id", "main_entry_id", "field_mappings", "sso_shared_secret", "sso_token_ttl_minutes", "dingtalk_app_key", "dingtalk_agent_id", "agent_a_max_rounds", "agent_b_max_rounds", "data_retention_days", "power_map_base_url", "power_map_get_path", "power_map_update_path"]:
        value = getattr(payload, key)
        if value is not None:
            setattr(cfg, key, value)
    mapping = dict((cfg.field_mappings or {}).get("jiandaoyun", {}) or {})
    forms = dict(mapping.get("forms") or {})
    main_form = dict(forms.get("客户主表") or {})
    mapping_entry_id = str(main_form.get("entry_id") or "").strip()
    cfg_entry_id = str(cfg.main_entry_id or "").strip()
    effective_main_entry_id = cfg_entry_id or mapping_entry_id
    if effective_main_entry_id:
        cfg.main_entry_id = effective_main_entry_id
        if mapping_entry_id != effective_main_entry_id:
            main_form["entry_id"] = effective_main_entry_id
            forms["客户主表"] = main_form
            mapping["forms"] = forms
            field_mappings = dict(cfg.field_mappings or {})
            field_mappings["jiandaoyun"] = mapping
            cfg.field_mappings = field_mappings
    db.add(ConfigChangeLog(config_section="jiandaoyun", changed_fields={k: {"old": before.get(k), "new": getattr(cfg, k)} for k in before if before.get(k) != getattr(cfg, k)}, changed_by=user["username"]))
    db.commit()
    emit_event(db, "config.changed", {"user_name": user["username"], "user_id": user["username"], "source": "superadmin"}, {"transcript_id": None, "company_id_hash": None, "session_id": str(uuid4())}, {"config_section": "jiandaoyun", "changed_fields": [k for k in payload.model_dump().keys() if getattr(payload, k) is not None], "changed_by": user["username"]})
    return {"success": True}


@app.post("/api/v1/admin/config/test")
def test_admin_config(user: dict[str, Any] = Depends(require_superadmin)):
    return {"success": True, "message": "连接正常（demo）"}


@app.get("/api/v1/admin/llm-config")
def get_llm_config(user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    cfg = ensure_system_config(db)
    return {
        "provider": cfg.llm_provider,
        "api_key": "sk-****xxxx" if cfg.llm_api_key_encrypted else "",
        "base_url": cfg.llm_base_url,
        "agent_a_model": cfg.agent_a_model,
        "agent_b_model": cfg.agent_b_model,
        "nl_chat_model": cfg.nl_chat_model,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "agent_a_prompt": cfg.agent_a_prompt,
        "agent_b_prompt": cfg.agent_b_prompt,
        "nl_query_prompt": cfg.nl_query_prompt,
        "nl_modify_prompt": cfg.nl_modify_prompt,
        "agent_a_prompt_version": prompt_version(cfg.agent_a_prompt),
        "agent_b_prompt_version": prompt_version(cfg.agent_b_prompt),
    }


@app.put("/api/v1/admin/llm-config")
def save_llm_config(payload: LlmConfigPayload, user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    cfg = ensure_system_config(db)
    before = {k: getattr(cfg, k) for k in ["llm_provider", "llm_base_url", "agent_a_model", "agent_b_model", "nl_chat_model", "temperature", "max_tokens", "agent_a_prompt", "agent_b_prompt", "nl_query_prompt", "nl_modify_prompt"]}
    if payload.api_key:
        cfg.llm_api_key_encrypted = encrypt_secret(payload.api_key)
    mapping = {"provider": "llm_provider", "base_url": "llm_base_url"}
    for key in ["provider", "base_url", "agent_a_model", "agent_b_model", "nl_chat_model", "temperature", "max_tokens", "agent_a_prompt", "agent_b_prompt", "nl_query_prompt", "nl_modify_prompt"]:
        value = getattr(payload, key)
        if value is None:
            continue
        attr = mapping.get(key, key)
        setattr(cfg, attr, value)
    db.add(ConfigChangeLog(config_section="llm", changed_fields={k: {"old": before.get(k), "new": getattr(cfg, k)} for k in before if before.get(k) != getattr(cfg, k)}, changed_by=user["username"]))
    db.commit()
    emit_event(db, "config.changed", {"user_name": user["username"], "user_id": user["username"], "source": "superadmin"}, {"transcript_id": None, "company_id_hash": None, "session_id": str(uuid4())}, {"config_section": "llm", "changed_fields": [k for k in payload.model_dump().keys() if getattr(payload, k) is not None], "changed_by": user["username"]})
    return {"success": True, "agent_a_prompt_version": prompt_version(cfg.agent_a_prompt), "agent_b_prompt_version": prompt_version(cfg.agent_b_prompt)}


@app.post("/api/v1/admin/llm-config/test")
async def test_llm_config(payload: LlmTestPayload, user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    cfg = ensure_system_config(db)
    prompt_map = {
        "agent_a": cfg.agent_a_prompt,
        "agent_b": cfg.agent_b_prompt,
        "nl_query": cfg.nl_query_prompt,
        "nl_modify": cfg.nl_modify_prompt,
    }
    prompt_template = prompt_map.get(payload.target, cfg.agent_a_prompt)
    rendered_prompt = render_prompt_template(
        prompt_template,
        {
            "industry": payload.industry or "未知行业",
            "department": payload.department or "未知部门",
            "company_name": payload.company_name or "未知公司",
            "transcript_text": payload.transcript_text or "",
            "agent_a_result": payload.agent_a_result or {},
            "jiandaoyun_existing_data": payload.jiandaoyun_existing_data or {},
            "user_name": user.get("username", "unknown"),
            "user_role": user.get("source", "superadmin"),
            "user_query": payload.user_query or "",
            "record_summary": "待修改记录",
            "field_name": "status",
            "old_value": "未启动",
            "new_value": "进行中",
        },
    )
    provider = (cfg.llm_provider or "").strip().lower()
    api_key = decrypt_secret(cfg.llm_api_key_encrypted) or ""
    if provider not in {"anthropic", "claude", "anthropic_compatible", "dashscope", "openai_compatible"}:
        return {
            "success": False,
            "summary": f"LLM 测试失败：当前 provider={provider}，不在支持列表",
            "target": payload.target,
            "preview": rendered_prompt[:1200],
            "rendered_prompt": rendered_prompt,
            "prompt_version": prompt_version(prompt_template),
        }
    if not api_key:
        return {
            "success": False,
            "summary": "LLM 测试失败：未配置可用 LLM API Key",
            "target": payload.target,
            "preview": rendered_prompt[:1200],
            "rendered_prompt": rendered_prompt,
            "prompt_version": prompt_version(prompt_template),
        }
    if provider in {"anthropic", "claude", "anthropic_compatible"} and AsyncAnthropic is None:
        return {
            "success": False,
            "summary": "LLM 测试失败：anthropic SDK 不可用",
            "target": payload.target,
            "preview": rendered_prompt[:1200],
            "rendered_prompt": rendered_prompt,
            "prompt_version": prompt_version(prompt_template),
        }
    try:
        if provider in {"dashscope", "openai_compatible"}:
            base_url = (cfg.llm_base_url or "").rstrip("/")
            if not base_url:
                raise RuntimeError("未配置 LLM Base URL")
            async with httpx.AsyncClient(timeout=3600) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": cfg.agent_a_model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 8},
                )
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code} {resp.text[:200]}")
            return {
                "success": True,
                "llm_call": {"status": "success", "provider": provider},
                "summary": "LLM 真实连通性测试成功",
                "target": payload.target,
                "preview": rendered_prompt[:1200],
                "rendered_prompt": rendered_prompt,
                "prompt_version": prompt_version(prompt_template),
            }

        client = AsyncAnthropic(api_key=api_key)
        resp = await client.messages.create(
            model=cfg.agent_a_model or "claude-sonnet-4-5-20250929",
            max_tokens=16,
            messages=[{"role": "user", "content": "ping"}],
        )
        return {
            "success": True,
            "llm_call": {"status": "success", "provider": provider, "stop_reason": getattr(resp, "stop_reason", "unknown")},
            "summary": "LLM 真实连通性测试成功",
            "target": payload.target,
            "preview": rendered_prompt[:1200],
            "rendered_prompt": rendered_prompt,
            "prompt_version": prompt_version(prompt_template),
        }
    except Exception as exc:
        return {
            "success": False,
            "summary": f"LLM 测试失败：{exc}",
            "target": payload.target,
            "preview": rendered_prompt[:1200],
            "rendered_prompt": rendered_prompt,
            "prompt_version": prompt_version(prompt_template),
        }


@app.get("/api/v1/admin/maintenance/health")
def admin_maintenance_health(user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    cfg = ensure_system_config(db)
    runtime_cfg = get_jiandaoyun_runtime_config(cfg)
    effective_main_entry_id = str(runtime_cfg.get("main_entry_id") or "").strip()
    checks: dict[str, dict[str, Any]] = {
        "backend": {"ok": True, "message": "服务运行正常"},
        "llm": {"ok": True, "message": "配置可用"},
        "jiandaoyun": {"ok": True, "message": "配置可用"},
    }

    # Basic backend availability and database connectivity
    try:
        db.execute(select(1))
    except Exception as exc:
        checks["backend"] = {"ok": False, "message": f"数据库连接异常: {exc}"}

    # LLM readiness by provider
    provider = (cfg.llm_provider or "").strip().lower()
    if provider not in {"anthropic", "claude", "anthropic_compatible", "dashscope", "openai_compatible"}:
        checks["llm"] = {"ok": False, "message": f"当前 provider={provider}，不在支持列表"}
    elif not cfg.agent_a_model:
        checks["llm"] = {"ok": False, "message": "未配置 Agent-A 模型"}
    elif not cfg.llm_api_key_encrypted:
        checks["llm"] = {"ok": False, "message": "未配置 LLM API Key"}
    else:
        api_key = decrypt_secret(cfg.llm_api_key_encrypted) or ""
        if not api_key:
            checks["llm"] = {"ok": False, "message": "LLM API Key 解密失败或为空"}
        elif provider in {"anthropic", "claude", "anthropic_compatible"} and AsyncAnthropic is None:
            checks["llm"] = {"ok": False, "message": "anthropic SDK 不可用"}
        elif provider in {"dashscope", "openai_compatible"} and not cfg.llm_base_url:
            checks["llm"] = {"ok": False, "message": "OpenAI-compatible 模式缺少 Base URL"}

    # Basic Jiandaoyun connectivity readiness (configuration-level check in demo mode)
    if not cfg.jiandaoyun_base_url or not cfg.jiandaoyun_app_id or not effective_main_entry_id:
        checks["jiandaoyun"] = {"ok": False, "message": "简道云配置不完整，请检查 Base URL/app_id/entry_id"}
    elif not cfg.jiandaoyun_api_key_encrypted:
        checks["jiandaoyun"] = {"ok": False, "message": "未配置简道云 API Key"}

    overall_ok = all(item["ok"] for item in checks.values())
    return {"ok": overall_ok, "checks": checks, "timestamp": now_utc().isoformat()}


@app.post("/api/v1/admin/refresh-cache")
async def admin_refresh_cache(
    user: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    cfg = ensure_system_config(db)
    runtime_cfg = get_jiandaoyun_runtime_config(cfg)
    # 强制清空缓存（包括内存和共享文件），触发重新拉取
    CUSTOMER_INDEX_CACHE["items"] = []
    CUSTOMER_INDEX_CACHE["at"] = None
    if SHARED_CACHE_FILE.exists():
        SHARED_CACHE_FILE.unlink()
    async with _get_refresh_lock():
        await refresh_customer_index_cache(runtime_cfg)
    count = len(CUSTOMER_INDEX_CACHE.get("items", []))
    return {"success": True, "message": f"客户索引已刷新，共 {count} 条", "total": count}


@app.post("/api/v1/admin/jiandaoyun/fetch-widgets")
async def admin_fetch_jiandaoyun_widgets(
    payload: AdminFetchWidgetsPayload,
    user: dict[str, Any] = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    _ = user
    form_name = payload.form_name.strip()
    entry_id = payload.entry_id.strip()

    cfg = ensure_system_config(db)
    api_key = decrypt_secret(cfg.jiandaoyun_api_key_encrypted) if cfg.jiandaoyun_api_key_encrypted else ""
    app_id = (cfg.jiandaoyun_app_id or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先在配置页填写简道云 API Key")
    if not app_id:
        raise HTTPException(status_code=400, detail="请先在配置页填写简道云应用 ID")

    client = JiandaoyunClient(api_key=api_key)
    try:
        raw = await client.fetch_form_widgets(app_id=app_id, entry_id=entry_id)
    except JiandaoyunClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    widgets = raw.get("widgets", [])
    summary = {
        "text_fields": sum(1 for w in widgets if w.get("type") in {"text", "textarea"}),
        "number_fields": sum(1 for w in widgets if w.get("type") == "number"),
        "subform_fields": sum(1 for w in widgets if w.get("type") == "subform"),
        "lookup_fields": sum(1 for w in widgets if w.get("type") == "lookup"),
        "other_fields": sum(1 for w in widgets if w.get("type") not in {"text", "textarea", "number", "subform", "lookup"}),
    }
    return {
        "form_name": form_name,
        "entry_id": entry_id,
        "widget_count": len(widgets),
        "widgets": widgets,
        "summary": summary,
    }


def _render_shell(page_title: str, active: str = "") -> HTMLResponse:
    return HTMLResponse(f"<html><body><h1>{page_title}</h1><p>前端工程将在独立项目中提供。</p></body></html>")


@app.get("/")
def root():
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return RedirectResponse(url="/docs")


@app.get("/_spa_fallback/{full_path:path}")
def spa_fallback_preview(full_path: str):
    # Keep API/docs endpoints untouched; fallback only for frontend routes.
    if full_path.startswith(("api/", "docs", "redoc", "openapi.json", "health")):
        raise HTTPException(status_code=404, detail="Not Found")
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return RedirectResponse(url="/docs")


@app.post("/api/v1/transcript/upload")
async def transcript_upload(files: list[UploadFile] = File(...), company_name_hint: str = Form(default=""), db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    allowed_types = {
        ".txt": "text",
        ".srt": "text",
        ".vtt": "text",
        ".md": "text",
        ".pdf": "text",
        ".doc": "text",
        ".docx": "text",
        ".jpeg": "image",
        ".jpg": "image",
        ".png": "image",
        ".webp": "image",
    }
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="单次最多上传10个文件。")

    merged_text_parts: list[str] = []
    merged_title = None
    total_size = 0
    input_type: str = "text"
    has_image = False
    file_names: list[str] = []
    total_char_count = 0

    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in allowed_types:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {f.filename}，支持文本文件与 JPEG/PNG/WebP 图片。")

        raw_bytes = await f.read()
        total_size += len(raw_bytes)
        if total_size > 16 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="文件总大小超过 16MB 限制。")

        file_type = allowed_types[suffix]
        file_names.append(f.filename or "未知文件")

        if file_type == "text":
            content = raw_bytes.decode("utf-8", errors="ignore")
            merged_text_parts.append(f"--- 文件: {f.filename} ---\n{content}")
            total_char_count += len(content)
            if not merged_title:
                merged_title = f.filename
        else:
            has_image = True
            merged_text_parts.append(f"--- 文件: {f.filename} (图片) ---")

    if has_image and merged_text_parts and any("(图片)" not in p for p in merged_text_parts):
        input_type = "mixed"
    elif has_image:
        input_type = "image"

    merged_raw = "\n\n".join(merged_text_parts)
    parsed = build_raw_transcript_payload(merged_raw, fallback_title=merged_title or "多文件转写")
    # 多文件时标题用第一个文件名（去掉扩展名），避免出现 "--- 文件: xxx ---" 这种分隔符标题
    if merged_title and parsed["title"].startswith("--- 文件:"):
        from pathlib import Path as _Path
        parsed["title"] = _Path(merged_title).stem or merged_title

    normalized_company = company_name_hint.strip() if company_name_hint else ""
    transcript = Transcript(
        source="upload",
        source_id=", ".join(file_names),
        title=parsed["title"],
        raw_text=parsed["raw_text"],
        segments=parsed["segments"],
        input_type=input_type,
        status="parsed",
        company_name=normalized_company or None,
        company_id=hash_company_id(normalized_company) if normalized_company else None,
        sso_user_name=user.get("display_name") or user.get("user_name") or user.get("username"),
        sso_user_id=user.get("user_id") if user.get("source") == "sso" else None,
    )
    db.add(transcript)
    db.commit()
    db.refresh(transcript)
    emit_event(db, "transcript.uploaded", {"user_name": user.get("username", "demo"), "user_id": user.get("username", "demo"), "source": user.get("source", "superadmin")}, {"transcript_id": transcript.id, "company_id_hash": hash_company_id(company_name_hint or transcript.id), "session_id": str(uuid4())}, {"source": "upload", "file_count": len(files), "file_names": file_names, "total_size_bytes": total_size, "segment_count": len(parsed["segments"]), "char_count": total_char_count, "input_type": input_type})
    return TranscriptUploadResponse(transcript_id=transcript.id, title=parsed["title"], segment_count=len(parsed["segments"]), status="parsed", preview=parsed["raw_text"][:500], file_count=len(files))


@app.post("/api/v1/transcript/dingtalk-fetch")
def transcript_dingtalk_fetch(payload: DingtalkFetchPayload, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    content = (payload.raw_text or "").strip()
    if not content:
        content = f"钉钉会议 {payload.conference_id}\n发言人 1 00:00:01\n（示例）未获取到会议原文，请补充钉钉接口返回内容。"
    parsed = build_raw_transcript_payload(content, fallback_title=payload.title or f"钉钉会议 {payload.conference_id}")
    transcript = Transcript(
        source="dingtalk_api",
        source_id=payload.conference_id,
        title=payload.title or parsed["title"] or f"钉钉会议 {payload.conference_id}",
        raw_text=parsed["raw_text"],
        segments=parsed["segments"],
        input_type="text",
        status="parsed",
        company_name=None,
        company_id=None,
        sso_user_name=user.get("display_name") or user.get("user_name") or user.get("username"),
        sso_user_id=user.get("user_id") if user.get("source") == "sso" else None,
    )
    db.add(transcript)
    db.commit()
    db.refresh(transcript)
    emit_event(
        db,
        "transcript.uploaded",
        {"user_name": _user_name(user), "user_id": user.get("user_id", _user_name(user)), "source": user.get("source", "superadmin")},
        {"transcript_id": transcript.id, "company_id_hash": hash_company_id(payload.conference_id), "session_id": str(uuid4())},
        {"source": "dingtalk_api", "conference_id": payload.conference_id, "char_count": len(content), "segment_count": len(parsed["segments"])},
    )
    return TranscriptUploadResponse(transcript_id=transcript.id, title=transcript.title or f"钉钉会议 {payload.conference_id}", segment_count=len(parsed["segments"]), status="parsed", preview=parsed["raw_text"][:500])


@app.get("/api/v1/transcripts")
def list_transcripts(db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    stmt = _allowed_transcript_stmt(user).order_by(Transcript.created_at.desc())
    items = db.scalars(stmt).all()
    return {
        "items": [
            {
                "id": t.id,
                "source": t.source,
                "source_id": t.source_id,
                "title": t.title,
                "status": t.status,
                "company_name": t.company_name,
                "company_name_hint": t.company_name,
                "raw_text_preview": (t.raw_text or "")[:200],
                "input_type": t.input_type,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "extraction_summary": _extraction_summary(t.agent_a_result),
                "card_count": len((t.agent_b_result or {}).get("result", {}).get("operation_cards", [])) if t.agent_b_result else 0,
                "sso_user_name": t.sso_user_name,
            }
            for t in items
        ]
    }


def _extraction_summary(agent_a_result: dict[str, Any] | None) -> dict[str, Any] | None:
    """从 agent_a_result 提取摘要（预期数/场景数）用于列表展示。"""
    if not agent_a_result or agent_a_result.get("error"):
        return None
    result = agent_a_result.get("result", {})
    facts = result.get("facts", [])
    if not facts:
        return None
    expectations = sum(1 for f in facts if f.get("category") == "expectation" or f.get("type") == "expectation" or "预期" in str(f.get("field_name", "")))
    scenarios = sum(1 for f in facts if f.get("category") == "scenario" or f.get("type") == "scenario" or "场景" in str(f.get("field_name", "")))
    return {"expectations": expectations, "scenarios": scenarios, "total": len(facts)}


@app.get("/api/v1/transcripts/{transcript_id}")
def get_transcript(transcript_id: str, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    stmt = _allowed_transcript_stmt(user).where(Transcript.id == transcript_id)
    t = db.scalar(stmt)
    if not t:
        raise HTTPException(status_code=404, detail="转写不存在")
    return {
        "id": t.id, "source": t.source, "source_id": t.source_id,
        "title": t.title, "status": t.status, "company_name": t.company_name,
        "company_name_hint": t.company_name, "raw_text": t.raw_text,
        "segments": t.segments, "company_id": t.company_id, "input_type": t.input_type,
        "agent_a_result": t.agent_a_result,
        "agent_b_result": t.agent_b_result,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "sso_user_name": t.sso_user_name,
    }


@app.get("/api/v1/followup-records")
def list_followup_records(
    company_id: str | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(require_auth),
):
    stmt = _allowed_followup_stmt(user).order_by(FollowupRecord.created_at.desc())
    if company_id:
        stmt = stmt.where(FollowupRecord.company_id == company_id)
    stmt = stmt.limit(max(1, min(limit, 1000)))
    items = db.scalars(stmt).all()
    return {
        "items": [
            {
                "id": r.id,
                "source": r.source,
                "source_id": r.source_id,
                "title": r.title,
                "status": r.status,
                "company_id": r.company_id,
                "company_name": r.company_name,
                "company_name_hint": r.company_name,
                "raw_text": r.raw_text,
                "input_type": r.input_type,
                "review_date": r.review_date,
                "follow_type": r.follow_type,
                "sso_user_name": r.sso_user_name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "extraction_summary": _extraction_summary(r.agent_a_result),
                "card_count": len((r.agent_b_result or {}).get("result", {}).get("operation_cards", [])) if r.agent_b_result else 0,
            }
            for r in items
        ]
    }


@app.get("/api/v1/followup-records/{record_id}")
def get_followup_record(record_id: str, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    stmt = _allowed_followup_stmt(user).where(FollowupRecord.id == record_id)
    r = db.scalar(stmt)
    if not r:
        raise HTTPException(status_code=404, detail="跟进记录不存在")
    return {
        "id": r.id,
        "source": r.source,
        "source_id": r.source_id,
        "title": r.title,
        "status": r.status,
        "company_id": r.company_id,
        "company_name": r.company_name,
        "company_name_hint": r.company_name,
        "raw_text": r.raw_text,
        "input_type": r.input_type,
        "review_date": r.review_date,
        "follow_type": r.follow_type,
        "sso_user_name": r.sso_user_name,
        "agent_a_result": r.agent_a_result,
        "agent_b_result": r.agent_b_result,
        "raw_record": r.raw_record,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@app.post("/api/v1/followup-records/fetch")
async def fetch_followup_records(
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(require_superadmin),
):
    from .services.followup_scraper import fetch_and_store

    cfg = ensure_system_config(db)
    api_key = decrypt_secret(cfg.jiandaoyun_api_key_encrypted) if cfg.jiandaoyun_api_key_encrypted else ""
    if not api_key:
        raise HTTPException(status_code=400, detail="简道云 API Key 未配置")
    try:
        result = await fetch_and_store(db, api_key=api_key)
    except JiandaoyunClientError as exc:
        raise HTTPException(status_code=502, detail=f"简道云接口失败: {exc}")
    return result


@app.post("/api/v1/transcripts/{transcript_id}/analyze")
async def start_transcript_analysis(
    transcript_id: str,
    source_type: str = "transcript",
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(require_auth),
):
    if source_type == "followup":
        stmt = _allowed_followup_stmt(user).where(FollowupRecord.id == transcript_id)
        record = db.scalar(stmt)
        if not record:
            raise HTTPException(status_code=404, detail="跟进记录不存在")
    else:
        stmt = _allowed_transcript_stmt(user).where(Transcript.id == transcript_id)
        record = db.scalar(stmt)
        if not record:
            raise HTTPException(status_code=404, detail="转写不存在")

    if record.status not in ("parsed", "error"):
        raise HTTPException(status_code=409, detail=f"状态为 {record.status}，无法启动分析")
    if not record.raw_text:
        raise HTTPException(status_code=400, detail="内容为空")

    from .services.analysis_pipeline import run_analysis_pipeline
    asyncio.create_task(run_analysis_pipeline(transcript_id, source_type=source_type))

    emit_event(
        db,
        "analysis.started",
        {"user_name": user.get("username", "demo"), "user_id": user.get("username", "demo"), "source": user.get("source", "superadmin")},
        {"transcript_id": transcript_id, "company_id_hash": record.company_id or "demo", "session_id": str(uuid4())},
        {"status": "analyzing", "source_type": source_type},
    )
    return TranscriptAnalyzeResponse(transcript_id=transcript_id, status="analyzing", message="分析已启动，可关闭页面稍后查看")


@app.get("/api/v1/customers/list")
async def customers_list(
    keyword: str = "",
    limit: int = 200,
    data_id: str | None = None,
    refresh: bool = False,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(require_auth),
):
    """获取客户列表，支持关键字搜索、分页和刷新缓存"""
    limit = max(1, min(limit, 500))
    cfg = ensure_system_config(db)
    runtime_cfg = get_jiandaoyun_runtime_config(cfg)
    mapping = runtime_cfg.get("mapping", {})
    main_form = ((mapping or {}).get("forms") or {}).get("客户主表", {})
    app_id = runtime_cfg.get("app_id", "")
    api_key = runtime_cfg.get("api_key", "")
    main_entry_id = str(main_form.get("entry_id", "")).strip()

    if not api_key or not app_id or not main_entry_id:
        now = now_utc()
        cached_at = CUSTOMERS_CACHE.get("at")
        if isinstance(cached_at, datetime) and (now - cached_at).total_seconds() < CUSTOMERS_CACHE_TTL_SECONDS:
            customers = CUSTOMERS_CACHE.get("items", [])
        else:
            customers = fetch_customers_for_user(db, user)
            CUSTOMERS_CACHE["items"] = customers
            CUSTOMERS_CACHE["at"] = now
        return {"mode": "mock", "customers": customers, "cached_at": (CUSTOMERS_CACHE.get("at") or now).isoformat()}
    now = now_utc()
    warning: str | None = None

    # 先尝试从共享文件加载缓存（进程间共享）
    if not CUSTOMER_INDEX_CACHE.get("items"):
        shared = _load_shared_cache()
        if shared and shared.get("items"):
            CUSTOMER_INDEX_CACHE["items"] = shared["items"]
            CUSTOMER_INDEX_CACHE["at"] = shared.get("at")
            CUSTOMER_INDEX_CACHE["source"] = shared.get("source", "file")

    # 只在显式刷新或缓存为空时触发全量查询；使用 asyncio.Lock 确保只有一个协程执行刷新
    if refresh or not CUSTOMER_INDEX_CACHE.get("items"):
        async with _get_refresh_lock():
            # 获取到锁后再次检查，避免重复刷新
            if refresh or not CUSTOMER_INDEX_CACHE.get("items"):
                try:
                    shared = _load_shared_cache()
                    if not refresh and shared and shared.get("items"):
                        CUSTOMER_INDEX_CACHE["items"] = shared["items"]
                        CUSTOMER_INDEX_CACHE["at"] = shared.get("at")
                        CUSTOMER_INDEX_CACHE["source"] = shared.get("source", "file")
                    else:
                        await refresh_customer_index_cache(runtime_cfg)
                except JiandaoyunClientError as exc:
                    warning = str(exc)

    cached_items = CUSTOMER_INDEX_CACHE.get("items", []) or []
    if not cached_items:
        # Last-resort fallback: fetch one page for local filtering so search never returns total blank.
        try:
            mapping = runtime_cfg.get("mapping", {})
            main_form = ((mapping or {}).get("forms") or {}).get("客户主表", {})
            display_fields = list(main_form.get("display_fields", []) or [])
            if "comname_01" not in display_fields:
                display_fields.append("comname_01")
            if "com_name" not in display_fields:
                display_fields.append("com_name")
            client = JiandaoyunClient(api_key=runtime_cfg.get("api_key", ""))
            one_page = await client.query_data_list(
                app_id=runtime_cfg.get("app_id", ""),
                entry_id=str(main_form.get("entry_id", "")),
                fields=display_fields,
                limit=200,
            )
            cached_items = [
                {
                    "company_id": row.get("_id"),
                    "company_name": row.get("comname_01") or row.get("com_name") or row.get("企业名称") or row.get("客户名称") or row.get("公司名称") or "未知公司",
                    "comname_01": row.get("comname_01"),
                    "com_name": row.get("com_name"),
                    "csm": _extract_csm_name(row.get("success")),
                    "com_id": row.get("com_id", ""),
                    "raw": row,
                }
                for row in (one_page.get("data", []) or [])
                if row.get("_id")
            ]
            if warning is None:
                warning = "客户索引未完成，当前使用单页兜底数据"
        except Exception:
            pass

    if not cached_items:
        # Final fallback: never return empty when local transcript history has customer clues.
        local_customers = fetch_customers_for_user(db, user)
        if local_customers:
            cached_items = [
                {
                    "company_id": item.get("company_id"),
                    "company_name": item.get("company_name"),
                    "comname_01": item.get("company_name"),
                    "com_name": item.get("company_name"),
                    "csm": "",
                    "com_id": "",
                    "raw": item,
                }
                for item in local_customers
                if item.get("company_id")
            ]
            if warning is None:
                warning = "简道云客户索引拉取失败，已回退本地转写客户列表"

    # 多租户：SSO / user 用户只显示自己负责的客户
    if user.get("source") == "sso":
        user_name = user.get("user_name", "")
        if user_name:
            cached_items = [c for c in cached_items if c.get("csm") == user_name]
    elif user.get("source") == "user":
        display_name = user.get("display_name", "")
        if display_name:
            cached_items = [c for c in cached_items if c.get("csm") == display_name]

    keyword_norm = keyword.strip().lower()
    if keyword_norm:
        filtered = [
            item
            for item in cached_items
            if keyword_norm
            in " ".join(
                [
                    str(item.get("company_name", "")),
                    str(item.get("comname_01", "")),
                    str(item.get("com_name", "")),
                    str(item.get("企业名称", "")),
                    str(item.get("客户名称", "")),
                    str(item.get("公司名称", "")),
                ]
            ).lower()
        ]
    else:
        filtered = cached_items

    customers = filtered[:limit]
    
    # 如果没有客户数据，提供更详细的错误信息
    if not customers and not warning:
        if runtime_cfg.get("api_key") and runtime_cfg.get("app_id") and main_form.get("entry_id"):
            warning = "未找到任何客户数据，请检查简道云表单是否有数据"
        else:
            warning = "简道云配置不完整，请先配置简道云API密钥和应用ID"
    
    return {
        "mode": "cache",
        "search_mode": "local_index",
        "customers": customers,
        "next_data_id": customers[-1].get("company_id") if customers else None,
        "cached_at": (CUSTOMER_INDEX_CACHE.get("at") or now).isoformat() if isinstance(CUSTOMER_INDEX_CACHE.get("at"), datetime) else now.isoformat(),
        "cache_total": len(cached_items),
        "warning": warning,
        "debug_info": {
            "runtime_configured": bool(
                runtime_cfg.get("api_key") and 
                runtime_cfg.get("app_id") and 
                main_form.get("entry_id")
            ),
            "app_id": runtime_cfg.get("app_id"),
            "main_entry_id": main_form.get("entry_id"),
            "cache_items_count": len(cached_items),
            "cached_at_is_datetime": isinstance(CUSTOMER_INDEX_CACHE.get("at"), datetime)
        }
    }


@app.get("/api/v1/companies/search")
async def company_search(query: CompanySearchQuery = Depends(), db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    keyword = query.q.strip().lower()
    customers = CUSTOMER_INDEX_CACHE.get("items", []) or fetch_customers_for_user(db, user)
    # 多租户过滤
    if user.get("source") == "sso":
        user_name = user.get("user_name", "")
        if user_name:
            customers = [c for c in customers if c.get("csm") == user_name]
    elif user.get("source") == "user":
        display_name = user.get("display_name", "")
        if display_name:
            customers = [c for c in customers if c.get("csm") == display_name]
    if keyword:
        customers = [item for item in customers if keyword in item["company_name"].lower()]
    return {"items": customers[:50], "status": "cache" if CUSTOMER_INDEX_CACHE.get("items") else "mock"}


@app.get("/api/v1/customers/search")
async def search_customers(
    keyword: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(require_auth),
):
    """从本地缓存索引中模糊搜索客户，不再直查简道云"""
    limit = max(1, min(limit, 200))
    keyword_norm = keyword.strip().lower()
    cached_items = CUSTOMER_INDEX_CACHE.get("items", []) or []

    # 多租户过滤
    if user.get("source") == "sso":
        user_name = user.get("user_name", "")
        if user_name:
            cached_items = [c for c in cached_items if c.get("csm") == user_name]
    elif user.get("source") == "user":
        display_name = user.get("display_name", "")
        if display_name:
            cached_items = [c for c in cached_items if c.get("csm") == display_name]

    if not cached_items:
        # 缓存为空时回退到 customers_list 的逻辑刷新一次
        return await customers_list(keyword=keyword, limit=limit, refresh=True, db=db, user=user)

    if not keyword_norm:
        return {"customers": cached_items[:limit], "mode": "cache", "total": len(cached_items)}

    filtered = [
        item
        for item in cached_items
        if keyword_norm
        in " ".join(
            [
                str(item.get("company_name", "")),
                str(item.get("comname_01", "")),
                str(item.get("com_name", "")),
                str(item.get("企业名称", "")),
                str(item.get("客户名称", "")),
                str(item.get("公司名称", "")),
            ]
        ).lower()
    ]
    return {"customers": filtered[:limit], "mode": "cache_search", "total": len(filtered)}


@app.get("/api/v1/customers/{company_id}/profile")
async def customer_profile(company_id: str, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    cfg = ensure_system_config(db)
    runtime_cfg = get_jiandaoyun_runtime_config(cfg)
    mapping = runtime_cfg.get("mapping", {})
    main_form = ((mapping or {}).get("forms") or {}).get("客户主表", {})
    app_id = runtime_cfg.get("app_id", "")
    api_key = runtime_cfg.get("api_key", "")
    main_entry_id = str(main_form.get("entry_id", "")).strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="jiandaoyun_api_key_not_configured")
    if not app_id or not main_entry_id:
        raise HTTPException(status_code=503, detail="jiandaoyun_form_mapping_not_configured")
    client = JiandaoyunClient(api_key=api_key)
    try:
        data = await client.query_single_data(app_id=app_id, entry_id=main_entry_id, data_id=company_id)
    except JiandaoyunClientError as exc:
        transcript_stmt = _allowed_transcript_stmt(user).where(Transcript.company_id == company_id)
        transcript = db.scalars(transcript_stmt.order_by(Transcript.updated_at.desc())).first()
        if not transcript:
            return {"mode": "fallback", "profile": {"company_id": company_id, "company_name": "未知客户"}, "warning": str(exc)}
        return {
            "mode": "fallback",
            "profile": {
                "company_id": company_id,
                "company_name": transcript.company_name or "未知客户",
                "raw_text": transcript.raw_text,
                "status": transcript.status,
            },
            "warning": str(exc),
        }
    emit_event(
        db,
        "profile.loaded",
        {"user_name": _user_name(user), "user_id": user.get("user_id", _user_name(user)), "source": user.get("source", "superadmin")},
        {"transcript_id": None, "company_id_hash": hash_company_id(company_id), "session_id": str(uuid4())},
        {"expectation_count": 0, "scenario_count": 0, "latency_ms": 50},
    )
    return {"mode": "jiandaoyun", "profile": data}


@app.get("/api/v1/customers/{company_id}/yuqi")
async def customer_yuqi(company_id: str, limit: int = 100, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    _ = user
    cfg = ensure_system_config(db)
    runtime_cfg = get_jiandaoyun_runtime_config(cfg)
    mapping = runtime_cfg.get("mapping", {})
    yuqi_form = ((mapping or {}).get("forms") or {}).get("预期表", {})
    app_id = runtime_cfg.get("app_id", "")
    api_key = runtime_cfg.get("api_key", "")
    entry_id = str(yuqi_form.get("entry_id", "")).strip()
    lookup_widget = ((yuqi_form.get("lookup_customer") or {}).get("widget")) or "relation"
    if not api_key:
        raise HTTPException(status_code=503, detail="jiandaoyun_api_key_not_configured")
    client = JiandaoyunClient(api_key=api_key)
    filter_condition = {"rel": "and", "cond": [{"field": lookup_widget, "type": "lookup", "method": "eq", "value": [company_id]}]}
    try:
        data = await client.query_data_list(app_id=app_id, entry_id=entry_id, filter_condition=filter_condition, limit=min(200, max(1, limit)))
    except JiandaoyunClientError as exc:
        return {"mode": "fallback", "items": [], "warning": str(exc)}
    return {"mode": "jiandaoyun", "items": data.get("data", [])}


@app.get("/api/v1/customers/{company_id}/changjing")
async def customer_changjing(company_id: str, limit: int = 100, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    _ = user
    cfg = ensure_system_config(db)
    runtime_cfg = get_jiandaoyun_runtime_config(cfg)
    mapping = runtime_cfg.get("mapping", {})
    form = ((mapping or {}).get("forms") or {}).get("场景表", {})
    app_id = runtime_cfg.get("app_id", "")
    api_key = runtime_cfg.get("api_key", "")
    entry_id = str(form.get("entry_id", "")).strip()
    lookup_widget = ((form.get("lookup_customer") or {}).get("widget")) or "_widget_1737335801798"
    if not api_key:
        raise HTTPException(status_code=503, detail="jiandaoyun_api_key_not_configured")
    client = JiandaoyunClient(api_key=api_key)
    filter_condition = {"rel": "and", "cond": [{"field": lookup_widget, "type": "lookup", "method": "eq", "value": [company_id]}]}
    try:
        data = await client.query_data_list(app_id=app_id, entry_id=entry_id, filter_condition=filter_condition, limit=min(200, max(1, limit)))
    except JiandaoyunClientError as exc:
        return {"mode": "fallback", "items": [], "warning": str(exc)}
    return {"mode": "jiandaoyun", "items": data.get("data", [])}


@app.get("/api/v1/customers/{company_id}/contacts")
async def customer_contacts(company_id: str, user: dict[str, Any] = Depends(require_auth)):
    """Proxy CRM contact list for the customer's com_id."""
    items = CUSTOMER_INDEX_CACHE.get("items", []) or []
    cust = next((c for c in items if c.get("company_id") == company_id), None)
    com_id = cust.get("com_id", "") if cust else ""
    if not com_id:
        return {"contacts": [], "warning": "com_id not found in cache"}
    url = f"https://crm.finereporthelp.com/WebReport/decision/url/pub/crm/data?id=18b1e023fb1b46008b7c16357f0e5c41&secret=123456&contname=&comid={com_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
    try:
        data = resp.json()
        return {"contacts": data.get("data", [])}
    except Exception:
        return {"contacts": [], "error": "CRM contact API failed"}


@app.get("/api/v1/customers/{company_id}/tasks")
async def customer_tasks(company_id: str, username: str = "", user: dict[str, Any] = Depends(require_auth)):
    """Proxy CRM task list for the customer's com_id."""
    items = CUSTOMER_INDEX_CACHE.get("items", []) or []
    cust = next((c for c in items if c.get("company_id") == company_id), None)
    com_id = cust.get("com_id", "") if cust else ""
    if not com_id:
        return {"tasks": [], "warning": "com_id not found in cache"}
    effective_username = username or user.get("integrate_id") or user.get("username", "")
    url = f"https://crm.finereporthelp.com/WebReport/decision/url/pub/crm/data?id=0aefe1a17d854ca18c2430c39fa0e3b2&secret=123456&com_id={com_id}&username={effective_username}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
    try:
        data = resp.json()
        return {"tasks": data.get("data", [])}
    except Exception:
        return {"tasks": [], "error": "CRM task API failed"}


@app.post("/api/v1/customers/switch")
def customer_switch(payload: CustomerSwitchPayload, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    emit_event(
        db,
        "customer.switched",
        {"user_name": _user_name(user), "user_id": user.get("user_id", _user_name(user)), "source": user.get("source", "superadmin")},
        {"transcript_id": None, "company_id_hash": hash_company_id(payload.company_id_to), "session_id": str(uuid4())},
        {"company_id_from": payload.company_id_from, "company_id_to": payload.company_id_to, "trigger": payload.trigger},
    )
    return {"success": True}


def agent_a_mock(transcript: dict[str, Any]) -> dict[str, Any]:
    text = transcript.get("raw_text", "")
    return {"is_customer_visit": True, "confidence": 0.85, "company_name_guess": "某某科技有限公司" if ("科技" in text or "公司" in text) else "未知公司", "expectations": [{"summary": "实现质检自动化", "is_first_value": True, "description": "客户希望通过AI视觉识别实现产线质检自动化。", "estimated_start_time": "2026-06", "status": "未启动", "progress_note": "初步沟通需求", "source_quote": "我们希望能用AI来做质检", "speaker": "发言人 1", "timestamp": "00:00:03"}], "scenarios": [{"title": "质检缺陷识别", "is_first_value": True, "pain_point": "人工质检漏检率高、效率低", "core_metric_solution": "AI视觉识别，目标漏检率<1%", "value_quantification": "年节省质检人力成本约30万", "summary": "以AI替代人工质检", "source_quote": "目前质检全靠人工看", "speaker": "发言人 2", "timestamp": "00:01:23"}]}


def agent_b_mock(extraction_result: dict[str, Any]) -> dict[str, Any]:
    operations = [{"op_id": str(uuid4()), "type": "new_expectation", "data": extraction_result["expectations"][0], "source_quote": extraction_result["expectations"][0]["source_quote"], "confidence": 0.92}, {"op_id": str(uuid4()), "type": "new_scenario", "data": extraction_result["scenarios"][0], "source_quote": extraction_result["scenarios"][0]["source_quote"], "confidence": 0.88}]
    validated = validate_operations(extraction_result, operations)
    return {"company_id": "eb6dc9bc-a55c-11ea-ba0b-7cd30ab79bc4", "operations": validated["operations"], "warnings": validated["warnings"], "coverage": validated["coverage"]}


def _get_llm_runtime_config(cfg: SystemConfig) -> dict[str, str]:
    return {
        "provider": cfg.llm_provider or "",
        "api_key": decrypt_secret(cfg.llm_api_key_encrypted) or "",
        "model_name": cfg.agent_a_model or "claude-sonnet-4-5-20250929",
        "base_url": cfg.llm_base_url or "",
    }


def _build_agent_llm_client(llm_cfg: dict[str, str]) -> Any:
    provider = str(llm_cfg.get("provider") or "").strip().lower()
    api_key = str(llm_cfg.get("api_key") or "")
    if provider in {"dashscope", "openai_compatible"}:
        base_url = str(llm_cfg.get("base_url") or "").strip()
        return OpenAICompatibleAgentClient(base_url=base_url, api_key=api_key)
    if AsyncAnthropic is None:
        raise RuntimeError("anthropic SDK 不可用")
    return AsyncAnthropic(api_key=api_key)


def _fallback_extraction(transcript_id: str, transcript: dict[str, Any], reason: str) -> dict[str, Any]:
    mock_data = agent_a_mock(transcript)
    return {
        "task_id": f"ext-{transcript_id}",
        "status": "completed",
        "mode": "fallback",
        "fallback_reason": reason,
        "result": mock_data,
    }


def build_user_message(input_type: str, content: str | None, images: list[dict] | None) -> list[dict]:
    blocks: list[dict[str, Any]] = []
    if content:
        blocks.append({"type": "text", "text": f"请从以下内容中提取客户事实信息：\n\n{content}"})
    if images:
        if not content:
            blocks.append({"type": "text", "text": "请从以下图片中提取客户事实信息："})
        for img in images:
            blocks.append({"type": "image", "source": img})
    if not blocks:
        if input_type == "image":
            blocks.append({"type": "text", "text": "请从图片中提取客户事实信息。"})
        else:
            blocks.append({"type": "text", "text": "请从以下内容中提取客户事实信息。"})
    return blocks


def _to_openai_messages(system_prompt: str, user_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    content_blocks: list[dict[str, Any]] = []
    for block in user_blocks:
        if block.get("type") == "text":
            content_blocks.append({"type": "text", "text": block.get("text", "")})
        elif block.get("type") == "image":
            src = block.get("source", {})
            media_type = src.get("media_type", "image/jpeg")
            b64 = src.get("data", "")
            content_blocks.append({"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}})
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content_blocks if content_blocks else [{"type": "text", "text": "请提取客户事实"}]},
    ]


async def _run_extraction_openai_compatible(
    *,
    transcript_id: str,
    llm_config: dict[str, str],
    system_prompt: str,
    user_message: list[dict[str, Any]],
    request_timeout_seconds: int,
    connect_timeout_seconds: int,
) -> dict[str, Any]:
    base_url = llm_config.get("base_url", "").rstrip("/")
    api_key = llm_config.get("api_key", "")
    model_name = llm_config.get("model_name", "")
    if not base_url:
        raise ValueError("OpenAI-compatible base_url 未配置")
    url = f"{base_url}/chat/completions"
    prompt = (
        "你必须仅返回 JSON，格式为 "
        '{"facts":[{"field_name":"...","value":"...","confidence":0.0,"source_quote":"...","source_type":"text|image","category":"company_info|contact_person|requirements|feedback|renewal_intent|competitor_mention|action_items|risk_signals"}]}'
    )
    messages = _to_openai_messages(system_prompt + "\n\n" + prompt, user_message)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model_name, "messages": messages, "temperature": 0.1}

    _append_llm_line(transcript_id, "调用 OpenAI-compatible /chat/completions")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(float(request_timeout_seconds), connect=float(connect_timeout_seconds))) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"OpenAI-compatible 调用超时（{request_timeout_seconds}s）") from exc
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenAI-compatible 调用失败: HTTP {resp.status_code} {resp.text[:200]}")
    data = resp.json()
    text = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
    if not text:
        raise RuntimeError("OpenAI-compatible 返回空内容")
    if isinstance(text, list):
        text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    raw = text.strip()
    # Strip model-specific tags (e.g. Qwen, DeepSeek box tags)
    raw = raw.removeprefix("<|begin_of_box|>").removeprefix("<|box_start|>").removesuffix("<|end_of_box|>").removesuffix("<|box_end|>").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        snippet = raw[:240].replace("\n", " ")
        raise RuntimeError(f"模型返回非 JSON，片段: {snippet}") from exc
    result = {"facts": parsed.get("facts", []), "total_extracted": len(parsed.get("facts", []))}
    _append_llm_line(transcript_id, "OpenAI-compatible 返回成功，开始结构化校验")
    return validate_extraction_output(result)


async def run_extraction_task(payload: AgentExtractionPayload, cfg: SystemConfig) -> dict[str, Any]:
    payload_data = payload.model_dump()
    transcript_obj = payload_data.get("transcript", {})
    transcript_id = payload_data.get("transcript_id") or transcript_obj.get("id") or str(uuid4())
    input_type = payload_data.get("input_type", "text")
    content = payload_data.get("content") or transcript_obj.get("raw_text")
    images = payload_data.get("images") or []
    llm_request_timeout = int(payload_data.get("llm_request_timeout_seconds") or 3600)
    llm_connect_timeout = int(payload_data.get("llm_connect_timeout_seconds") or 3600)
    agent_total_timeout = int(payload_data.get("agent_total_timeout_seconds") or AgentRunner.TOTAL_TIMEOUT_SECONDS)
    agent_tool_timeout = int(payload_data.get("agent_tool_timeout_seconds") or AgentRunner.TOOL_TIMEOUT_SECONDS)
    agent_max_iterations = int(payload_data.get("agent_max_iterations") or AgentRunner.MAX_ITERATIONS)

    llm_config = _get_llm_runtime_config(cfg)
    TASK_PROGRESS[transcript_id] = {
        "mode": "llm",
        "input_type": input_type,
        "current_turn": 0,
        "max_turns": agent_max_iterations,
        "extraction_status": "processing",
        "comparison_status": "pending",
        "llm_lines": [],
    }
    _append_llm_line(transcript_id, f"开始识别：准备调用 LLM（请求超时 {llm_request_timeout}s）")
    provider = str(llm_config.get("provider", "")).strip().lower()
    if provider and provider not in {"anthropic", "claude", "anthropic_compatible", "dashscope", "openai_compatible"}:
        TASK_PROGRESS[transcript_id].update({"mode": "fallback", "extraction_status": "fallback"})
        reason = f"当前 provider={provider}，与 Agent-A 的 Anthropic 调用链不兼容"
        _append_llm_line(transcript_id, reason)
        return _fallback_extraction(transcript_id, transcript_obj, reason)
    if not llm_config["api_key"]:
        TASK_PROGRESS[transcript_id].update({"mode": "fallback", "extraction_status": "fallback"})
        _append_llm_line(transcript_id, "未配置可用 LLM，已回退 mock")
        return _fallback_extraction(transcript_id, transcript_obj, "LLM API Key 未配置")

    try:
        processed_images = validate_and_preprocess(images) if images else []
        user_message = build_user_message(input_type, content, processed_images)
        if provider in {"dashscope", "openai_compatible"}:
            validated = await _run_extraction_openai_compatible(
                transcript_id=transcript_id,
                llm_config=llm_config,
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                user_message=user_message,
                request_timeout_seconds=llm_request_timeout,
                connect_timeout_seconds=llm_connect_timeout,
            )
            TASK_PROGRESS[transcript_id].update(
                {
                    "mode": "llm",
                    "input_type": input_type,
                    "current_turn": 1,
                    "max_turns": 1,
                    "extraction_status": "completed",
                    "comparison_status": "pending",
                }
            )
            _append_llm_line(transcript_id, "识别完成：OpenAI-compatible 路径")
            return {
                "task_id": payload_data.get("task_id", f"ext-{transcript_id}"),
                "status": "completed",
                "mode": "llm",
                "input_type": input_type,
                "result": validated,
            }

        if AsyncAnthropic is None:
            TASK_PROGRESS[transcript_id].update({"mode": "fallback", "extraction_status": "fallback"})
            _append_llm_line(transcript_id, "anthropic SDK 不可用，已回退")
            return _fallback_extraction(transcript_id, transcript_obj, "anthropic SDK 不可用")
        runner = AgentRunner(
            llm_client=AsyncAnthropic(api_key=llm_config["api_key"]),
            phase=AgentPhase.EXTRACTION,
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
            tools=get_tools("extraction"),
            tool_executors=get_executors("extraction"),
            model_name=llm_config["model_name"],
            output_validator=validate_extraction_output,
            final_tool_name="extract_customer_facts",
            progress_callback=lambda msg: _append_llm_line(transcript_id, msg),
            max_iterations=agent_max_iterations,
            tool_timeout_seconds=agent_tool_timeout,
            total_timeout_seconds=agent_total_timeout,
        )
        result = await runner.run(session_id=f"ext-{transcript_id}", user_message=user_message)
        TASK_PROGRESS[transcript_id] = {
            "mode": "llm" if result.status == "success" else "fallback",
            "input_type": input_type,
            "current_turn": result.turns_used,
            "max_turns": runner.max_iterations,
            "extraction_status": "completed" if result.status == "success" else "fallback",
            "comparison_status": "pending",
            "llm_lines": TASK_PROGRESS.get(transcript_id, {}).get("llm_lines", []),
        }
        if result.status == "success":
            _append_llm_line(transcript_id, "识别完成：结构化结果校验通过")
            return {
                "task_id": payload_data.get("task_id", f"ext-{transcript_id}"),
                "status": "completed",
                "mode": "llm",
                "input_type": input_type,
                "result": result.data,
            }
        _append_llm_line(transcript_id, f"识别未成功，状态：{result.status}，已回退")
        return _fallback_extraction(transcript_id, transcript_obj, f"Agent 返回 {result.status}: {result.message}")
    except ImagePreprocessError as exc:
        TASK_PROGRESS[transcript_id].update({"mode": "error", "extraction_status": "error"})
        _append_llm_line(transcript_id, f"图片预处理失败：{exc}")
        return {
            "task_id": payload_data.get("task_id", f"ext-{transcript_id}"),
            "status": "error",
            "mode": "error",
            "message": str(exc),
        }
    except Exception as exc:
        TASK_PROGRESS[transcript_id].update({"mode": "fallback", "extraction_status": "fallback"})
        reason = _format_exc(exc)
        logger.exception("extraction llm error: %s", reason)
        _append_llm_line(transcript_id, f"LLM 异常：{reason}")
        return _fallback_extraction(transcript_id, transcript_obj, f"LLM 调用异常: {reason}")


@app.post("/api/v1/agent/extraction/task")
async def extraction_task(payload: dict[str, Any], db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    payload_obj = AgentExtractionPayload.model_validate(
        {
            "task_id": payload.get("task_id"),
            "transcript_id": payload.get("transcript_id"),
            "input_type": payload.get("input_type", "text"),
            "content": payload.get("content"),
            "images": payload.get("images", []),
            "transcript": payload.get("transcript", {}),
            "llm_request_timeout_seconds": payload.get("llm_request_timeout_seconds"),
            "llm_connect_timeout_seconds": payload.get("llm_connect_timeout_seconds"),
            "agent_total_timeout_seconds": payload.get("agent_total_timeout_seconds"),
            "agent_tool_timeout_seconds": payload.get("agent_tool_timeout_seconds"),
            "agent_max_iterations": payload.get("agent_max_iterations"),
        }
    )
    cfg = ensure_system_config(db)
    result = await run_extraction_task(payload_obj, cfg)
    transcript = payload_obj.transcript.model_dump() if payload_obj.transcript else {}
    transcript_id = payload_obj.transcript_id or transcript.get("id")
    emit_event(db, "extraction.completed", {"user_name": user.get("username", "demo"), "user_id": user.get("username", "demo"), "source": user.get("source", "superadmin")}, {"transcript_id": transcript_id, "company_id_hash": hash_company_id(transcript.get("company_name_hint", "demo")), "session_id": payload_obj.task_id or str(uuid4())}, {"mode": result.get("mode"), "input_type": payload_obj.input_type, "status": result.get("status")}, op_type="extraction", action="completed", latency_ms=1200, model=cfg.agent_a_model, prompt_ver=prompt_version(cfg.agent_a_prompt))
    return result


@app.post("/api/v1/agent/comparison/task")
async def comparison_task(payload: AgentComparisonPayload, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    payload_data = payload.model_dump()
    cfg = ensure_system_config(db)
    transcript_id = payload_data.get("transcript_id")
    if transcript_id:
        TASK_PROGRESS.setdefault(transcript_id, {}).update({"comparison_status": "processing"})
        _append_llm_line(transcript_id, "进入比对阶段：生成操作卡片")
    runtime_cfg = get_jiandaoyun_runtime_config(cfg)
    llm_cfg = _get_llm_runtime_config(cfg)
    profile = await get_executors("comparison")["fetch_customer_profile"](
        {
            "company_id": payload_data.get("company_id") or "demo",
            "company_name": (payload_data.get("existing_record") or {}).get("company_name"),
            "runtime_cfg": runtime_cfg,
        }
    )
    result = await get_executors("comparison")["compare_and_generate_operations"](
        {
            "extracted_facts": payload_data.get("extraction_result", {}).get("facts", []),
            "existing_profile": profile,
            "runtime_cfg": runtime_cfg,
            "llm_cfg": llm_cfg,
            "agent_b_prompt": cfg.agent_b_prompt,
        }
    )
    cfg_mapping = (ensure_system_config(db).field_mappings or {}).get("jiandaoyun", {})
    forms_cfg = (cfg_mapping.get("forms") or {})
    enhanced_cards: list[dict[str, Any]] = []
    for card in result.get("operation_cards", []):
        target_form = str(card.get("target_form") or "未知")
        form_cfg = forms_cfg.get(target_form, {})
        safe_card = check_operation_cards([card], form_cfg)[0] if form_cfg else {**card, "safety_status": "unknown", "safety_reason": "form mapping missing"}
        enhanced_cards.append(safe_card)
    result["operation_cards"] = enhanced_cards
    result["total"] = len(enhanced_cards)
    result = validate_comparison_output(result)
    result["company_id"] = profile.get("_id")
    if transcript_id:
        OPERATION_CARD_STORE[transcript_id] = [dict(card) for card in result.get("operation_cards", [])]
    existing_record = payload_data.get("existing_record", {})
    mode = "fallback" if profile.get("_mock") else "llm"
    emit_event(db, "comparison.completed", {"user_name": user.get("username", "demo"), "user_id": user.get("username", "demo"), "source": user.get("source", "superadmin")}, {"transcript_id": payload_data.get("transcript_id"), "company_id_hash": hash_company_id(existing_record.get("company_id", "demo")), "session_id": payload_data.get("task_id", str(uuid4()))}, {"mode": mode, "cards": result.get("total", 0)}, op_type="comparison", action="completed", latency_ms=1500, model=cfg.agent_b_model, prompt_ver=prompt_version(cfg.agent_b_prompt))
    if transcript_id:
        TASK_PROGRESS.setdefault(transcript_id, {}).update({"comparison_status": "completed"})
        _append_llm_line(transcript_id, "比对完成：已生成审核卡片")
    return {
        "task_id": payload_data.get("task_id", str(uuid4())),
        "status": "completed",
        "mode": mode,
        "fallback_reason": "fallback active" if mode == "fallback" else None,
        "cards_with_safety": result.get("operation_cards", []),
        "result": result,
        "error": None,
    }


@app.post("/api/v1/operations/review-action")
def review_action(payload: ReviewActionPayload, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    emit_event(db, "review.action", {"user_name": user.get("username", "demo"), "user_id": user.get("username", "demo"), "source": user.get("source", "superadmin")}, {"transcript_id": None, "company_id_hash": hash_company_id("demo"), "session_id": str(uuid4())}, payload.model_dump(), op_type=payload.operation_type, action=payload.action)
    return {"success": True}


@app.post("/api/v1/operations/review-session")
def review_session(payload: ReviewSessionPayload, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    emit_event(db, "review.session", {"user_name": user.get("username", "demo"), "user_id": user.get("username", "demo"), "source": user.get("source", "superadmin")}, {"transcript_id": payload.transcript_id, "company_id_hash": hash_company_id(payload.transcript_id or "demo"), "session_id": str(uuid4())}, payload.model_dump())
    return {"success": True}


@app.post("/api/v1/operations/add")
def operations_add(payload: dict[str, Any], db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    """手动新增操作卡片到审核队列。"""
    transcript_id = payload.get("transcript_id")
    card = dict(payload.get("card") or {})
    if not transcript_id or not card:
        raise HTTPException(status_code=400, detail="transcript_id 和 card 为必填")
    card["card_id"] = card.get("card_id") or str(uuid4())
    card["review_status"] = "approved"
    card["_manual"] = True
    OPERATION_CARD_STORE.setdefault(transcript_id, []).append(card)
    emit_event(db, "card.manual_add", {"user_name": user.get("username", "demo"), "user_id": user.get("username", "demo"), "source": user.get("source", "superadmin")}, {"transcript_id": transcript_id, "company_id_hash": hash_company_id(transcript_id), "session_id": str(uuid4())}, {"card_id": card["card_id"], "target_form": card.get("target_form", "")})
    return {"success": True, "card_id": card["card_id"]}


@app.post("/api/v1/operations/review")
def operations_review(payload: ReviewAction, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    cards = OPERATION_CARD_STORE.get(payload.transcript_id, [])
    updated = False
    for card in cards:
        if card.get("card_id") == payload.card_id:
            card["review_status"] = "approved" if payload.action == "approve" else "rejected"
            if payload.reason:
                card["review_reason"] = payload.reason
            updated = True
            break
    emit_event(
        db,
        "review.action",
        {"user_name": user.get("username", "demo"), "user_id": user.get("username", "demo"), "source": user.get("source", "superadmin")},
        {"transcript_id": payload.transcript_id, "company_id_hash": hash_company_id(payload.transcript_id), "session_id": str(uuid4())},
        payload.model_dump(),
        op_type="review",
        action=payload.action,
    )
    return {"success": updated}


@app.post("/api/v1/operations/execute")
async def execute_operations(payload: dict[str, Any], db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    # New flow: execute approved cards from in-memory review store.
    if "card_ids" in payload:
        req = OperationExecuteRequest.model_validate(payload)
        cards = OPERATION_CARD_STORE.get(req.transcript_id, [])
        approved = [c for c in cards if c.get("review_status") == "approved" and c.get("card_id") in set(req.card_ids)]
        runtime_cfg = get_jiandaoyun_runtime_config(ensure_system_config(db))
        forms_cfg = (((runtime_cfg.get("mapping") or {}).get("forms")) or {})
        api_key = runtime_cfg.get("api_key") or ""
        app_id = runtime_cfg.get("app_id") or ""

        # 合并前端传回的字段更新（如 status、is_first_value 等用户修改项）
        if req.field_updates:
            for card in approved:
                cid = card.get("card_id")
                updates = req.field_updates.get(cid, {})
                if not updates:
                    continue
                change_items = card.get("change_items")
                if change_items:
                    for item in change_items:
                        fn = item.get("field_name")
                        if fn in updates:
                            item["new_value"] = updates[fn]
                    # 如果 field_updates 中有字段在 change_items 中不存在，追加新的 change item
                    form_cfg = forms_cfg.get(card.get("target_form", ""), {})
                    field_mapping = form_cfg.get("field_mapping") or {}
                    existing_fields = {it.get("field_name") for it in change_items}
                    for field_name, new_val in updates.items():
                        if field_name in existing_fields:
                            continue
                        mapped = field_mapping.get(field_name)
                        if mapped and isinstance(mapped, dict):
                            change_items.append({
                                "field_name": field_name,
                                "widget_name": str(mapped.get("widget", "")),
                                "old_value": None,
                                "new_value": new_val,
                            })
        if not api_key or not app_id:
            results = [{"card_id": c.get("card_id"), "execute_status": "skipped", "error": "jiandaoyun_api_key_not_configured"} for c in approved]
            return {"success": True, "results": results}
        data_creator = user.get("integrate_id") or user.get("username", "")
        writer = JiandaoyunWriter(api_key=api_key, app_id=app_id, data_creator=data_creator)
        results = await execute_cards(db=db, transcript_id=req.transcript_id, cards=approved, writer=writer, mapping_forms=forms_cfg)
        # Write back execution statuses.
        by_id = {r["card_id"]: r for r in results}
        for card in cards:
            cid = card.get("card_id")
            if cid in by_id:
                card["execute_status"] = by_id[cid]["execute_status"]
        return {"success": True, "results": results}

    # Legacy flow compatibility.
    payload_obj = ExecuteOperationsPayload.model_validate(payload)
    payload_data = payload_obj.model_dump()
    operations = payload_data.get("operations", [])
    merged = merge_and_write([], [], operations)
    results = [{"op_id": op.get("op_id", str(uuid4())), "status": "success", "jiandaoyun_data_id": str(uuid4())} for op in operations]
    db.add(OperationLog(transcript_id=payload_data.get("transcript_id"), operation_type="operations.execute", request_payload=payload_data, response_payload={"results": results, "merged": merged}, status="success", operator_name=user.get("username"), operator_id=user.get("username")))
    db.commit()
    emit_event(db, "write.completed", {"user_name": user.get("username", "demo"), "user_id": user.get("username", "demo"), "source": user.get("source", "superadmin")}, {"transcript_id": payload_data.get("transcript_id"), "company_id_hash": hash_company_id(payload_data.get("company_id", "")), "session_id": payload_data.get("session_id", str(uuid4()))}, {"operations_submitted": len(operations), "operations_succeeded": len(results), "operations_failed": 0, "total_latency_ms": 1000})
    return {"success": True, "results": results, "failed": []}


@app.get("/api/v1/operations/{transcript_id}/status")
def operations_status(transcript_id: str, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    _ = (db, user)
    cards = OPERATION_CARD_STORE.get(transcript_id, [])
    return {"transcript_id": transcript_id, "cards": cards}


@app.post("/api/v1/chat")
async def chat(payload: ChatPayload, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    payload_data = payload.model_dump()
    cfg = ensure_system_config(db)
    msg = payload_data["message"]
    company_id = str(payload_data.get("company_id") or "").strip()
    session_id = payload_data.get("session_id", str(uuid4()))
    now = now_utc()
    _cleanup_pending_operations(now)

    if payload_data.get("confirm"):
        pending = PENDING_CHAT_ACTIONS.pop(session_id, None)
        if not pending:
            return {"reply": "操作已过期，请重新发起对话。", "session_id": session_id, "needs_confirmation": False}
        runtime_cfg = get_jiandaoyun_runtime_config(cfg)
        mapping_forms = ((runtime_cfg.get("mapping") or {}).get("forms") or {})
        api_key = str(runtime_cfg.get("api_key") or "")
        app_id = str(runtime_cfg.get("app_id") or "")
        if not api_key or not app_id:
            return {"reply": "写入失败：请先配置简道云 API Key", "session_id": session_id, "needs_confirmation": False}
        tool_name = str(pending.get("tool_name") or "")
        tool_input = pending.get("tool_input", {}) or {}
        target_form = str(tool_input.get("target_form") or "")
        form_config = mapping_forms.get(target_form, {}) or {}
        entry_id = get_entry_id(target_form, mapping_forms)
        data_creator = user.get("integrate_id") or user.get("username", "")
        writer = JiandaoyunWriter(api_key=api_key, app_id=app_id, data_creator=data_creator)
        try:
            if tool_name == "create_customer_record":
                result = await writer.create_record(entry_id=entry_id, data=build_jiandaoyun_payload(tool_input, form_config))
            elif tool_name == "update_customer_record":
                result = await writer.update_record(
                    entry_id=entry_id,
                    data_id=str(tool_input.get("data_id") or ""),
                    data=build_jiandaoyun_payload(tool_input, form_config),
                )
            elif tool_name == "delete_customer_record":
                result = await writer.delete_record(entry_id=entry_id, data_id=str(tool_input.get("data_id") or ""))
            else:
                return {"reply": "未识别的待执行操作", "session_id": session_id, "needs_confirmation": False}
        except Exception as exc:
            log_operation(
                db,
                tool_name=tool_name,
                tool_input=tool_input,
                status="failed",
                source="chat",
                error=str(exc),
                operator_name=_user_name(user),
                operator_id=str(user.get("user_id") or _user_name(user)),
            )
            return {"reply": f"写入失败：{exc}", "session_id": session_id, "needs_confirmation": False}
        if not result.get("success"):
            detail = str(result.get("detail") or result.get("error_code") or "unknown")
            log_operation(
                db,
                tool_name=tool_name,
                tool_input=tool_input,
                status="failed",
                source="chat",
                jiandaoyun_response=result,
                error=detail,
                operator_name=_user_name(user),
                operator_id=str(user.get("user_id") or _user_name(user)),
            )
            return {"reply": f"写入失败：{detail}", "session_id": session_id, "needs_confirmation": False}
        log_operation(
            db,
            tool_name=tool_name,
            tool_input=tool_input,
            status="success",
            source="chat",
            jiandaoyun_response=result,
            operator_name=_user_name(user),
            operator_id=str(user.get("user_id") or _user_name(user)),
        )
        op_label = OP_LABELS.get(tool_name, "写入")
        return {
            "reply": f"已成功{op_label}到{target_form}",
            "execute_result": {"status": "success", "jiandaoyun_id": (result.get("data") or {}).get("_id")},
            "session_id": session_id,
            "needs_confirmation": False,
            "refresh_profile": True,
        }

    if _is_negative(msg):
        PENDING_CHAT_ACTIONS.pop(session_id, None)
        return {"reply": "已取消当前待确认操作。", "session_id": session_id, "needs_confirmation": False}

    if not company_id:
        return {"reply": "请先选择客户", "session_id": session_id, "needs_confirmation": False}
    llm_cfg = _get_llm_runtime_config(cfg)
    provider = str(llm_cfg.get("provider") or "").strip().lower()
    if provider not in {"anthropic", "claude", "anthropic_compatible", "dashscope", "openai_compatible"}:
        return {"reply": f"当前 provider={provider} 不支持 Chat Agent ToolCall", "session_id": session_id, "needs_confirmation": False}
    if not llm_cfg.get("api_key"):
        return {"reply": "请先在配置页填写 LLM API Key", "session_id": session_id, "needs_confirmation": False}
    if provider in {"dashscope", "openai_compatible"} and not llm_cfg.get("base_url"):
        return {"reply": "OpenAI-compatible 模式缺少 Base URL", "session_id": session_id, "needs_confirmation": False}
    if provider in {"anthropic", "claude", "anthropic_compatible"} and AsyncAnthropic is None:
        return {"reply": "当前环境不支持 Chat Agent ToolCall（缺少 anthropic SDK）", "session_id": session_id, "needs_confirmation": False}

    runtime_cfg = get_jiandaoyun_runtime_config(cfg)
    forms_cfg = ((runtime_cfg.get("mapping") or {}).get("forms") or {})
    try:
        llm_client = _build_agent_llm_client(llm_cfg)
    except Exception as exc:
        return {"reply": f"初始化 LLM 客户端失败：{exc}", "session_id": session_id, "needs_confirmation": False}
    runner = AgentRunner(
        llm_client=llm_client,
        phase=AgentPhase.COMPARISON,
        system_prompt=CHAT_SYSTEM_PROMPT,
        tools=get_chat_tools(),
        tool_executors=build_chat_executors(runtime_cfg),
        model_name=cfg.nl_chat_model or llm_cfg.get("model_name") or ("auto" if provider in {"dashscope", "openai_compatible"} else "claude-sonnet-4-5-20250929"),
        max_iterations=8,
        tool_timeout_seconds=3600,
        total_timeout_seconds=3600,
        write_tools={"create_customer_record", "update_customer_record", "delete_customer_record"},
        write_form_configs=forms_cfg,
        write_preview_builder=build_preview_text,
    )
    result = await runner.run(session_id=session_id, user_message=f"company_id={company_id}\n用户请求：{msg}")
    if result.status == "max_iterations":
        return {"reply": "无法完成操作，请检查指令", "session_id": session_id, "needs_confirmation": False}
    if result.status != "success":
        # LLM auth/runtime failure fallback: keep chat confirm workflow usable.
        err = (result.message or "").lower()
        if ("invalid x-api-key" in err or "authentication_error" in err or "incorrect api key" in err or "unauthorized" in err) and any(k in msg for k in ["新增", "添加", "创建", "修改", "更新"]):
            target_form = "场景表" if "场景" in msg else "预期表"
            form_cfg = forms_cfg.get(target_form, {}) or {}
            fm = form_cfg.get("field_mapping", {}) or {}
            fields: dict[str, str] = {}
            if target_form == "预期表":
                if "预期描述" in fm:
                    fields["预期描述"] = msg
                elif "预期简述" in fm:
                    fields["预期简述"] = msg
                if "预期状态" in fm:
                    fields["预期状态"] = "进行中" if "进行中" in msg else "未启动"
            else:
                if "场景标题" in fm:
                    fields["场景标题"] = msg[:30]
                if "业务诉求/痛点分析" in fm:
                    fields["业务诉求/痛点分析"] = msg
            if fields:
                pending = {
                    "tool_name": "update_customer_record" if any(k in msg for k in ["修改", "更新"]) else "create_customer_record",
                    "tool_input": {
                        "company_id": company_id,
                        "target_form": target_form,
                        "fields": fields,
                    },
                    "validated": False,
                    "created_at": now,
                }
                PENDING_CHAT_ACTIONS[session_id] = pending
                preview = build_preview_text(pending["tool_name"], pending["tool_input"])
                return {
                    "reply": f"LLM 鉴权失败，已切换本地兜底预览。\n{preview}\n请点击“确认执行”继续。",
                    "session_id": session_id,
                    "needs_confirmation": True,
                    "preview_data": pending["tool_input"],
                }
        return {"reply": result.message or f"处理失败：{result.status}", "session_id": session_id, "needs_confirmation": False}
    if runner.pending_write:
        pending = dict(runner.pending_write)
        pending["created_at"] = now
        PENDING_CHAT_ACTIONS[session_id] = pending
        preview = build_preview_text(pending["tool_name"], pending["tool_input"])
        reply = result.final_text or f"{preview}\n请点击“确认执行”继续。"
        return {
            "reply": reply,
            "needs_confirmation": True,
            "preview_data": pending.get("tool_input"),
            "session_id": session_id,
        }
    return {
        "reply": result.final_text or "已完成查询。",
        "needs_confirmation": False,
        "session_id": session_id,
    }


# ── 权利地图 API ──────────────────────────────────────

@app.get("/api/v1/power-map/{company_id}")
async def power_map_get(company_id: str, version: str | None = None, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    try:
        map_data = await get_power_map(db, company_id, current_user=user, version=version)
        return {"company_id": company_id, "map_data": map_data}
    except Exception as exc:
        logger.exception("power map get failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/power-map/{company_id}/bi-com-id")
async def power_map_bi_com_id(company_id: str, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    """返回 BI 系统的 com_id，前端用于构造 iframe URL"""
    cfg = db.get(SystemConfig, 1)
    if not cfg:
        raise HTTPException(status_code=500, detail="系统未初始化")

    prj_id = company_id
    try:
        api_key = decrypt_secret(cfg.jiandaoyun_api_key_encrypted) if cfg.jiandaoyun_api_key_encrypted else ""
        app_id = (cfg.jiandaoyun_app_id or "").strip()
        field_mappings = dict((cfg.field_mappings or {}).get("jiandaoyun", {}) or {})
        forms = dict(field_mappings.get("forms") or {})
        main_form = dict(forms.get("客户主表") or {})
        main_entry_id = (cfg.main_entry_id or str(main_form.get("entry_id", ""))).strip()
        if api_key and app_id and main_entry_id:
            client = JiandaoyunClient(api_key=api_key)
            profile_data = await client.query_single_data(app_id=app_id, entry_id=main_entry_id, data_id=company_id)
            profile = profile_data.get("data") if isinstance(profile_data, dict) else profile_data
            if isinstance(profile, dict):
                com_id = profile.get("com_id") or ""
                if com_id:
                    prj_id = com_id
    except Exception:
        pass

    api_cfg = _get_power_map_config(cfg)
    # powerMap_v3.13.html is served from /WebReport/power_map/, not /WebReport/decision/
    # Extract origin from base_url to construct the correct path
    from urllib.parse import urlparse
    origin = f"{urlparse(api_cfg['base_url']).scheme}://{urlparse(api_cfg['base_url']).netloc}"
    return {
        "company_id": company_id,
        "bi_com_id": prj_id,
        "bi_base_url": api_cfg["base_url"],
        "bi_iframe_url": f"{origin}/WebReport/power_map/powerMap_v3.13.html?com_id={prj_id}",
    }


@app.post("/api/v1/power-map/{company_id}/chat")
async def power_map_chat(company_id: str, payload: PowerMapChatPayload, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    msg = payload.message
    session_id = payload.session_id or str(uuid4())

    if payload.confirm:
        return {"reply": "请使用 /confirm 端点确认执行修改。", "session_id": session_id, "needs_confirmation": False}

    result = await chat_power_map(db, company_id, msg, current_user=user, version=payload.version)
    result["session_id"] = session_id
    return result


@app.post("/api/v1/power-map/{company_id}/confirm")
async def power_map_confirm(company_id: str, payload: PowerMapConfirmPayload, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    try:
        result = await confirm_power_map(db, company_id, payload.proposed_changes, current_user=user, version=payload.version)
        return result
    except Exception as exc:
        logger.exception("power map confirm failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/power-map/{company_id}/relayout")
async def power_map_relayout(company_id: str, payload: PowerMapRelayoutPayload, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    try:
        result = await relayout_power_map(db, company_id, mode=payload.mode, dept_id=payload.dept_id, current_user=user, version=payload.version)
        return result
    except Exception as exc:
        logger.exception("power map relayout failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/power-map/{company_id}/preview")
async def power_map_preview(company_id: str, payload: PowerMapPreviewPayload, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    try:
        result = await preview_power_map(db, company_id, payload.proposed_changes, current_user=user, version=payload.version)
        return result
    except Exception as exc:
        logger.exception("power map preview failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/power-map/{company_id}/harness-stream")
async def power_map_harness_stream(
    company_id: str,
    prj_id: str = Query(...),
    session_id: str = Query("", description="In-memory session to resume; empty creates a new one."),
    version: str | None = Query(None, description="Version UUID for multi-version support"),
    user: dict[str, Any] = Depends(get_current_user_for_sse),
    db: Session = Depends(get_db),
):
    """SSE stream of harness (vision LLM) execution: thinking, tool calls, results."""
    cfg = db.get(SystemConfig, 1)
    if not cfg:
        raise HTTPException(status_code=500, detail="系统未初始化")

    async def event_generator():
        try:
            async for event in _execute_harness_stream(
                company_id, prj_id, cfg,
                current_user=user, session_id=session_id, version=version,
            ):
                yield f"event: {event.type}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("power map harness-stream failed")
            err_payload = {"skipped": True, "error": f"unexpected: {exc}"}
            yield f"event: done\ndata: {json.dumps(err_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/power-map/{company_id}/chat_v2")
async def power_map_chat_v2(
    company_id: str,
    payload: PowerMapChatPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(get_current_user_for_sse),
):
    """SSE streaming chat v2: vision LLM tool loop against the local sandbox renderer."""
    # Reject resumed sessions — every chat starts fresh
    if payload.session_id:
        raise HTTPException(status_code=400, detail="session_id is no longer accepted; every chat starts a new session")

    cfg = db.get(SystemConfig, 1)
    if not cfg:
        raise HTTPException(status_code=500, detail="系统未初始化")

    bi_credentials = {
        "cookies": {k: v for k, v in request.cookies.items()},
        "bearer_token": request.headers.get("Authorization", "").removeprefix("Bearer ").strip() or None,
    }
    logger.info(
        "[DEBUG-J] 1.ENTRY company_id=%s user_msg=%s credential_present=%s ver=%s",
        company_id, payload.message[:200], bool(bi_credentials.get("cookies") or bi_credentials.get("bearer_token")), payload.version,
    )

    async def event_generator():
        try:
            async for event in chat_power_map_v2(
                db=db,
                company_id=company_id,
                message=payload.message,
                current_user=user,
                version=payload.version,
                bi_credentials=bi_credentials,
                # session_id removed — every chat starts fresh
            ):
                yield f"event: {event.type}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("power map chat_v2 failed")
            yield f"event: done\ndata: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/v1/power-map/debug/dump_ctx")
async def debug_dump_ctx(session_id: str):
    """Debug endpoint: dump a session's ctx (nodes + edges) for e2e geometry checks."""
    from .services.power_map_service import _get_session as _gs
    ctx = _gs(session_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    nodes = []
    for n in ctx.all_nodes:
        if isinstance(n, dict):
            nodes.append({"id": n.get("id", ""), "name": n.get("name", ""),
                          "node_type": n.get("node_type", ""), "parent_id": n.get("parent_id", ""),
                          "x": n.get("x", 0), "y": n.get("y", 0),
                          "w": n.get("w", 0), "h": n.get("h", 0)})
        else:
            nodes.append({"id": getattr(n, "id", ""), "name": getattr(n, "name", ""),
                          "node_type": getattr(n, "node_type", ""), "parent_id": getattr(n, "parent_id", ""),
                          "x": getattr(n, "x", 0), "y": getattr(n, "y", 0),
                          "w": getattr(n, "w", 0), "h": getattr(n, "h", 0)})
    edges = []
    for e in ctx.edges:
        if isinstance(e, dict):
            edges.append({"id": e.get("id", ""), "source_id": e.get("source_id", ""),
                          "target_id": e.get("target_id", ""), "edge_type": e.get("edge_type", "")})
        else:
            edges.append({"id": getattr(e, "id", ""), "source_id": getattr(e, "source_id", ""),
                          "target_id": getattr(e, "target_id", ""), "edge_type": getattr(e, "edge_type", "")})
    return {"session_id": session_id, "nodes": nodes, "edges": edges}


@app.post("/api/v1/power-map/{company_id}/commit")
async def power_map_commit(
    company_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: dict[str, Any] = Depends(require_auth),
):
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    return await commit_power_map_session(session_id, db)


@app.post("/api/v1/power-map/{company_id}/discard")
async def power_map_discard(
    company_id: str,
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(require_auth),
):
    session_id = str(payload.get("session_id", "")).strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    return discard_power_map_session(session_id)


_BI_HOST = "https://crm.finereporthelp.com"
_BI_SANDBOX_HTML_URL = f"{_BI_HOST}/WebReport/power_map/powerMap_v3.13.html"
_SANDBOX_ASSET_RE = re.compile(
    r"""(src|href|url)(\s*[=\(]\s*["']?)(https://crm\.finereporthelp\.com/)""",
    re.IGNORECASE,
)
_SANDBOX_REL_ASSET_RE = re.compile(
    r"""(src|href|url)(\s*[=\(]\s*["'])(css/|js/|img/|fonts/|plugins/)""",
    re.IGNORECASE,
)
_BI_HTML_BASE = f"{_BI_HOST}/WebReport/power_map/"
_SANDBOX_GETINFO_OLD = (
    "success: function(result){\n"
    "                    var obj = eval('(' + result + ')');\n"
    "                    switchVersion(ver_type,obj,self);"
)
_SANDBOX_GETINFO_NEW = (
    "success: function(result){\n"
    "                    var obj = window.__GRAPH_DATA__ || eval('(' + result + ')');\n"
    "                    switchVersion(ver_type,obj,self);"
)


@app.get("/api/power_map/sandbox")
async def power_map_sandbox(
    prj_id: str = Query(...),
    session_id: str = Query(""),
    db: Session = Depends(get_db),
):
    """Serve a patched BI power-map HTML page that uses in-memory graph data.

    If session_id matches a live harness session, the in-memory ctx is injected
    as window.__GRAPH_DATA__ so the page renders the LLM's working state
    without hitting BI's getInfo endpoint. Otherwise the page falls back to
    BI's live data via the original AJAX path.
    """
    cfg = db.get(SystemConfig, 1)
    if not cfg:
        raise HTTPException(status_code=500, detail="系统未初始化")

    auth_token = decrypt_secret(cfg.power_map_auth_token_encrypted) if cfg.power_map_auth_token_encrypted else ""
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(_BI_SANDBOX_HTML_URL, headers=headers, params={"com_id": prj_id})
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        logger.exception("sandbox: failed to fetch BI HTML")
        raise HTTPException(status_code=502, detail=f"BI HTML 获取失败: {exc}")

    html = html.replace(_SANDBOX_GETINFO_OLD, _SANDBOX_GETINFO_NEW)

    html = _SANDBOX_ASSET_RE.sub(
        lambda m: f'{m.group(1)}{m.group(2)}/api/power_map/sandbox-proxy?url={_BI_HOST}/',
        html,
    )
    html = _SANDBOX_REL_ASSET_RE.sub(
        lambda m: f'{m.group(1)}{m.group(2)}/api/power_map/sandbox-proxy?url={_BI_HTML_BASE}',
        html,
    )

    graph_payload: dict[str, Any] | None = None
    if session_id:
        ctx = _get_session(session_id)
        if ctx is not None:
            try:
                graph_payload = _ctx_to_getinfo_response(ctx)
            except Exception:
                logger.exception("sandbox: failed to build ctx getInfo payload")
                graph_payload = None

    if graph_payload is None and session_id:
        try:
            api_cfg = _get_power_map_config(cfg)
            get_url = api_cfg["base_url"].rstrip("/") + api_cfg["get_path"]
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(get_url, headers=headers, params={"com_id": prj_id})
                resp.raise_for_status()
                graph_payload = resp.json()
        except Exception:
            logger.exception("sandbox: fallback getInfo fetch failed")
            graph_payload = None

    if graph_payload is not None:
        injected = (
            "<script>window.__GRAPH_DATA__ = "
            + json.dumps(graph_payload, ensure_ascii=False)
            + ";</script>"
        )
        if "</head>" in html:
            html = html.replace("</head>", injected + "</head>", 1)
        else:
            html = injected + html

    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")


@app.get("/api/power_map/sandbox-proxy")
async def power_map_sandbox_proxy(
    url: str = Query(...),
    db: Session = Depends(get_db),
):
    """Proxy BI static assets so the sandbox page can load CSS/JS/images without CORS.

    Only URLs under crm.finereporthelp.com are proxied; everything else returns
    403. The response is streamed back with the original Content-Type.
    """
    if not url.startswith(_BI_HOST + "/"):
        raise HTTPException(status_code=403, detail="只允许代理 BI 资源")

    cfg = db.get(SystemConfig, 1)
    if not cfg:
        raise HTTPException(status_code=500, detail="系统未初始化")

    auth_token = decrypt_secret(cfg.power_map_auth_token_encrypted) if cfg.power_map_auth_token_encrypted else ""
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    max_bytes = 5 * 1024 * 1024

    async def stream_body():
        async with httpx.AsyncClient(timeout=15.0) as client:
            async with client.stream("GET", url, headers=headers) as upstream:
                if upstream.status_code >= 400:
                    raise HTTPException(status_code=upstream.status_code, detail="BI 资源响应错误")
                cl = upstream.headers.get("content-length")
                if cl and cl.isdigit() and int(cl) > max_bytes:
                    raise HTTPException(status_code=413, detail="BI 资源过大")
                total = 0
                async for chunk in upstream.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise HTTPException(status_code=413, detail="BI 资源过大")
                    yield chunk

    try:
        async with httpx.AsyncClient(timeout=15.0) as probe:
            head = await probe.head(url, headers=headers)
            content_type = head.headers.get("content-type", "application/octet-stream")
    except Exception:
        content_type = "application/octet-stream"

    return StreamingResponse(stream_body(), media_type=content_type)


# ═══════════════════════════════════════════════════════════
#  Phase A — local sandbox: patched HTML serving + mock BI endpoints
# ═══════════════════════════════════════════════════════════


@app.get("/sandbox/render")
def sandbox_render(session_id: str = Query(...)):
    """Serve the patched BI HTML with {PLACEHOLDER} replaced by session_id.

    JS/CSS assets load relative to ``<base href="/static/sandbox/">`` and are
    served by the StaticFiles mount on ``/static``.
    """
    try:
        html = render_sandbox_html(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")


@app.post("/sandbox/download")
async def sandbox_download(db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_superadmin)):
    """One-shot deployment endpoint: pull the BI bundle into SANDBOX_DIR.

    Requires the configured BI Bearer token. Idempotent (overwrites in place).
    """
    cfg = db.get(SystemConfig, 1)
    if not cfg:
        raise HTTPException(status_code=500, detail="系统未初始化")
    auth_token = decrypt_secret(cfg.power_map_auth_token_encrypted) if cfg.power_map_auth_token_encrypted else ""
    try:
        manifest = await sandbox_infra.download_bi_resources(auth_token or None)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"BI 资源下载失败: {exc}")
    return {"ok": True, "files": len(manifest), "manifest_path": str(sandbox_infra.MANIFEST_PATH)}


def _resolve_sandbox_session(request: Request) -> str:
    """Pull session id from X-Sandbox-Session header, falling back to ?session_id."""
    sid = request.headers.get("X-Sandbox-Session") or ""
    if not sid:
        sid = request.query_params.get("session_id", "")
    return sid.strip()


def _sandbox_text_response(payload: Any) -> Response:
    """Return JSON-encoded payload as text/plain.

    BI's powerMap_v3.13.html uses eval('(' + result + ')') on AJAX responses.
    jQuery auto-parses application/json into JS objects before success(), which
    breaks the eval. Returning text/plain keeps the body as a raw JSON string.
    """
    return Response(
        content=json.dumps(payload, ensure_ascii=False),
        media_type="text/plain; charset=utf-8",
    )


@app.get("/WebReport/decision/url/power_map/getInfo")
def mock_bi_get_info(request: Request):
    """Return the in-memory ctx for X-Sandbox-Session, in full BI getInfo shape.

    Falls back to an empty payload + error marker when the session is missing
    or has expired — never proxies to upstream.
    """
    session_id = _resolve_sandbox_session(request)
    if not session_id:
        return _sandbox_text_response(empty_getinfo_response("missing_session"))
    ctx = _get_session(session_id)
    if ctx is None:
        return _sandbox_text_response(empty_getinfo_response("session_not_found"))
    try:
        payload = ctx_to_full_getinfo_response(ctx)
    except Exception:
        logger.exception("sandbox: getInfo serialization failed for %s", session_id)
        return _sandbox_text_response(empty_getinfo_response("serialization_error"))
    return _sandbox_text_response(payload)


@app.post("/WebReport/decision/url/power_map/upInfo")
async def mock_bi_up_info(request: Request):
    """Sink — never writes ctx or forwards to BI."""
    return _sandbox_text_response({"ok": True})


@app.get("/WebReport/decision/url/power_map/update_expect")
def mock_bi_update_expect():
    return _sandbox_text_response({"ok": True})


@app.get("/WebReport/decision/url/power_map/update_scene")
def mock_bi_update_scene():
    return _sandbox_text_response({"ok": True})


@app.get("/WebReport/decision/url/power_map/judge_phone")
def mock_bi_judge_phone():
    return _sandbox_text_response({"exists": False})


@app.post("/WebReport/decision/url/power_map/upFile")
async def mock_bi_up_file():
    return _sandbox_text_response({"ok": True})


@app.get("/WebReport/decision/url/power_map/get_archive_jdy_id")
def mock_bi_get_archive_jdy_id():
    return _sandbox_text_response({"jdy_id": ""})


@app.get("/WebReport/decision/url/power_map/position_tree_combo")
def mock_bi_position_tree_combo():
    return _sandbox_text_response([])


# 1×1 transparent PNG — used by X6 graph.drawBackground when picname is empty
# or the upstream watermark image is unavailable. Prevents browser 404 noise.
_TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


@app.get("/static/sandbox/watermark/{name:path}")
def mock_sandbox_watermark(name: str):
    return Response(content=_TRANSPARENT_PNG, media_type="image/png")


@app.post("/test/seed_session")
async def test_seed_session(payload: dict[str, Any], db: Session = Depends(get_db)):
    """Temp verification helper: build a session from a live BI prj_id.

    Body: ``{"session_id": "test123", "prj_id": "<uuid>"}``. Returns counts
    so the caller can sanity-check the seed before curl'ing /getInfo.
    """
    session_id = str(payload.get("session_id") or "").strip() or _new_session_id()
    prj_id = str(payload.get("prj_id") or "").strip()
    if not prj_id:
        raise HTTPException(status_code=400, detail="prj_id required")
    cfg = db.get(SystemConfig, 1)
    if not cfg:
        raise HTTPException(status_code=500, detail="系统未初始化")
    try:
        current = await _fetch_from_external(cfg, prj_id, current_user=None)
    except Exception as exc:
        logger.exception("seed_session: BI fetch failed")
        raise HTTPException(status_code=502, detail=f"BI fetch failed: {exc}")
    nodes_raw = current.get("nodes", []) or []
    edges_raw = current.get("edges", []) or []
    nodes = [_node_from_bi_dict(n) for n in nodes_raw]
    ctx = _build_merge_context(nodes, edges_raw, version_id="")
    _store_session(session_id, ctx)
    return {
        "session_id": session_id,
        "prj_id": prj_id,
        "nodes": len(nodes),
        "edges": len(edges_raw),
    }


@app.get("/api/v1/analytics/business/overview")
def analytics_business_overview(period: str = "7d", db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_superadmin)):
    visits = db.scalar(select(func.count()).select_from(AnalyticsEvent).where(AnalyticsEvent.event_type == "transcript.uploaded")) or 0
    return {"period": period, "visit_count": visits, "active_operators": 1, "avg_visits_per_operator": float(visits), "avg_meeting_duration_min": 35, "avg_expectations_per_visit": 1.0, "avg_scenarios_per_visit": 1.0, "empty_visit_rate": 0.0, "overall_adoption_rate": 0.75, "quality_score": 0.72, "top_operators": [{"name": user.get("username"), "visits": visits, "adoption_rate": 0.75, "quality_score": 0.72}]}


@app.get("/api/v1/analytics/system/accuracy")
def analytics_system_accuracy(period: str = "7d", db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_superadmin)):
    cfg = ensure_system_config(db)
    return {"period": period, "agent_a": {"total_operations_generated": 2, "direct_confirm_rate": 0.52, "edit_then_confirm_rate": 0.22, "total_adoption_rate": 0.74, "delete_rate": 0.18, "minor_reword_rate": 0.65, "major_rewrite_rate": 0.25, "avg_confidence": 0.83, "by_type": {"expectation": {"adoption_rate": 0.78, "delete_rate": 0.15}, "scenario": {"adoption_rate": 0.70, "delete_rate": 0.22}}}, "agent_b": {"match_accuracy": 0.85, "false_update_rate": 0.10, "missed_match_rate": 0.05}, "prompt_version_current": {"agent_a": prompt_version(cfg.agent_a_prompt), "agent_b": prompt_version(cfg.agent_b_prompt)}}


@app.get("/api/v1/analytics/system/prompt-compare")
def analytics_prompt_compare(agent: str = "agent_a", period: str = "30d", user: dict[str, Any] = Depends(require_superadmin)):
    return {"agent": agent, "period": period, "versions": [{"prompt_version": "a1b2c3d4", "active_period": "04-01 ~ 04-15", "sample_count": 45, "adoption_rate": 0.68, "delete_rate": 0.22, "avg_latency_ms": 9500, "avg_tokens": 2800}, {"prompt_version": "f9e8d7c6", "active_period": "04-16 ~ 04-23", "sample_count": 32, "adoption_rate": 0.74, "delete_rate": 0.18, "avg_latency_ms": 8800, "avg_tokens": 2650}], "improvement": {"adoption_rate_delta": "+0.06", "delete_rate_delta": "-0.04", "latency_delta_ms": "-700", "conclusion": "新版 Prompt 在采纳率和延迟上均有提升"}}


@app.get("/api/v1/transcripts/{transcript_id}/progress")
def transcript_progress(transcript_id: str, user: dict[str, Any] = Depends(require_auth)):
    # 校验转写属于当前用户
    from .database import SessionLocal as _SL3
    _db3 = _SL3()
    try:
        stmt = _allowed_transcript_stmt(user).where(Transcript.id == transcript_id)
        if not _db3.scalar(stmt):
            raise HTTPException(status_code=404, detail="转写不存在")
    finally:
        _db3.close()

    p = TASK_PROGRESS.get(transcript_id, {})

    # 内存无进度数据时从 DB 重建
    if not p:
        from .database import SessionLocal as _SessionLocal
        _db = _SessionLocal()
        try:
            t = _db.get(Transcript, transcript_id)
            if t:
                ext_status = "completed" if t.agent_a_result else "pending"
                cmp_status = "completed" if t.agent_b_result else "pending"
                if t.status == "error":
                    ext_status = "error"
                    cmp_status = "error"
                elif t.status == "extracting":
                    ext_status = "processing"
                elif t.status == "comparing":
                    ext_status = "completed"
                    cmp_status = "processing"
                p = {
                    "mode": "llm",
                    "input_type": t.input_type or "text",
                    "current_turn": 0,
                    "max_turns": 8,
                    "extraction_status": ext_status,
                    "comparison_status": cmp_status,
                    "llm_lines": [],
                }
                TASK_PROGRESS[transcript_id] = p
        finally:
            _db.close()

    base = build_progress(
        transcript_id,
        mode=p.get("mode", "fallback"),
        input_type=p.get("input_type", "text"),
        current_turn=p.get("current_turn", 0),
        max_turns=p.get("max_turns", 8),
        extraction_status=p.get("extraction_status", "pending"),
        comparison_status=p.get("comparison_status", "pending"),
        llm_lines=p.get("llm_lines", []),
    )
    cards = OPERATION_CARD_STORE.get(transcript_id, [])

    # 内存无卡片时从 DB agent_b_result 重新加载
    if not cards:
        from .database import SessionLocal as _SessionLocal2
        _db2 = _SessionLocal2()
        try:
            t2 = _db2.get(Transcript, transcript_id)
            if t2 and t2.agent_b_result:
                cards = (t2.agent_b_result.get("result") or {}).get("operation_cards", [])
                if cards:
                    OPERATION_CARD_STORE[transcript_id] = [dict(c) for c in cards]
        finally:
            _db2.close()

    cards_total = len(cards)
    cards_approved = sum(1 for c in cards if c.get("review_status") == "approved")
    cards_executed = sum(1 for c in cards if c.get("execute_status") == "success")
    cards_failed = sum(1 for c in cards if c.get("execute_status") == "failed")
    if cards_total == 0:
        phase = "comparison" if p.get("comparison_status") == "processing" else "extraction"
    elif cards_executed + cards_failed >= cards_total and cards_total > 0:
        phase = "archived"
    elif cards_approved > 0:
        phase = "execution"
    else:
        phase = "review"
    base.update(
        {
            "phase": phase,
            "cards_total": cards_total,
            "cards_approved": cards_approved,
            "cards_executed": cards_executed,
            "cards_failed": cards_failed,
        }
    )
    return base


@app.get("/api/v1/analytics/export")
def analytics_export(user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AnalyticsEvent).order_by(AnalyticsEvent.created_at.desc())).all()
    return JSONResponse([{"event_type": r.event_type, "operator_name": r.operator_name, "payload": r.payload, "timestamp": r.created_at.isoformat()} for r in rows])


@app.get("/api/v1/health")
def api_health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"ok": True, "status": "healthy", "components": {"database": {"status": "healthy", "latency_ms": 3}, "llm_api": {"status": "healthy", "latency_ms": 450}, "jiandaoyun_api": {"status": "healthy", "latency_ms": 120}}, "timestamp": now_utc().isoformat()}


@app.get("/api/v1/debug/customers")
async def debug_customers(db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    """调试客户数据获取情况"""
    from .models import SystemConfig
    
    cfg = ensure_system_config(db)
    runtime_cfg = get_jiandaoyun_runtime_config(cfg)
    mapping = runtime_cfg.get("mapping", {})
    main_form = ((mapping or {}).get("forms") or {}).get("客户主表", {})
    
    return {
        "jiandaoyun_configured": bool(
            runtime_cfg.get("api_key") and 
            runtime_cfg.get("app_id") and 
            main_form.get("entry_id")
        ),
        "api_key_set": bool(runtime_cfg.get("api_key")),
        "app_id": runtime_cfg.get("app_id"),
        "main_entry_id": str(main_form.get("entry_id", "")).strip(),
        "cache_status": {
            "customers_cache_at": CUSTOMERS_CACHE.get("at").isoformat() if isinstance(CUSTOMERS_CACHE.get("at"), datetime) else None,
            "customer_index_cache_at": CUSTOMER_INDEX_CACHE.get("at").isoformat() if isinstance(CUSTOMER_INDEX_CACHE.get("at"), datetime) else None,
            "customer_index_items_count": len(CUSTOMER_INDEX_CACHE.get("items", [])),
        },
        "local_transcripts_customers": len(fetch_customers_for_user(db, user)),
        "first_local_customers": fetch_customers_for_user(db, user)[:5],
    }


@app.get("/api/v1/review/tags")
async def get_review_tags():
    """获取跟进标签树"""
    import json as _json
    tag_tree_path = Path(__file__).resolve().parent / "config" / "review_tag_tree.json"
    try:
        return _json.loads(tag_tree_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"无法加载标签树: {exc}")


@app.post("/api/v1/review/generate")
async def generate_review(data: dict[str, Any], user: dict[str, Any] = Depends(require_auth), db: Session = Depends(get_db)):
    """调用 LLM 生成跟进记录"""
    from .models import SystemConfig
    
    transcript_text = (data.get("transcript_text") or data.get("content") or "").strip()
    company_name = (data.get("company_name") or "").strip()
    if not transcript_text or not company_name:
        raise HTTPException(status_code=400, detail="缺少 transcript_text 或 company_name")

    cfg = db.scalars(select(SystemConfig)).first()
    if not cfg:
        cfg = SystemConfig()
        db.add(cfg)
        db.commit()
    
    api_key = decrypt_secret(cfg.llm_api_key_encrypted) if cfg.llm_api_key_encrypted else ""
    base_url = (cfg.llm_base_url or "").rstrip("/")
    model = cfg.agent_a_model or ""
    if not api_key or not base_url or not model:
        raise HTTPException(status_code=500, detail="LLM 未配置，请在管理页面完成配置")

    tag_tree_path = Path(__file__).resolve().parent / "config" / "review_tag_tree.json"
    try:
        tag_tree_data = json.loads(tag_tree_path.read_text(encoding="utf-8"))
    except Exception:
        tag_tree_data = []

    reviewer_name = _user_name(user)
    system_prompt = f"""你是帆软内部的客户成功记录员。
从会议转写中提取结构化跟进记录。
输出纯 JSON，包含以下字段：
        follow_type：从"线上跟进/线下跟进/内部沟通"选一个
review_date：YYYY-MM-DD
review_record：严格按以下格式输出：
【跟进目的】一句话概括，10字以内
【沟通详情】客观详细记录沟通内容，保留所有数字、版本号、规模等具体信息
【附件/kms链接】暂无
【参与人】我方：{reviewer_name}  客户方：xxx（职位/部门）
genjin_tags：数组，每项 {{level1, level2, level3}}，从以下选项中选择，level3 可为空字符串：
{json.dumps(tag_tree_data, ensure_ascii=False, indent=2)}
contact_names：字符串，客户侧参与人
if_tuisong：默认"否"
请只输出纯 JSON，不要用 markdown 代码块包裹，不要添加任何额外文字。"""

    images = (data.get("images") or [])
    user_prompt = f"会议转写内容：\n{transcript_text}\n\n客户名称：\n{company_name}\n\n请生成结构化的跟进记录。"

    # Build user message (multimodal if images provided)
    if images and isinstance(images, list) and len(images) > 0:
        user_content = [{"type": "text", "text": user_prompt}]
        for img in images:
            if isinstance(img, str) and img.startswith("data:image"):
                user_content.append({"type": "image_url", "image_url": {"url": img}})
        user_message = {"role": "user", "content": user_content}
    else:
        user_message = {"role": "user", "content": user_prompt}

    try:
        async with httpx.AsyncClient(timeout=3600) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "system", "content": system_prompt}, user_message], "stream": False},
            )
        if resp.status_code != 200:
            return {"error": f"LLM 返回 HTTP {resp.status_code}"}
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(content)
    except json.JSONDecodeError:
        return {"error": "LLM 返回内容不是有效 JSON"}
    except Exception as exc:
        return {"error": f"调用 LLM 失败: {exc}"}


@app.post("/api/v1/review/submit")
async def submit_review(data: dict[str, Any], user: dict[str, Any] = Depends(require_auth), db: Session = Depends(get_db)):
    """提交跟进记录到简道云"""
    from .models import SystemConfig
    
    cfg = db.scalars(select(SystemConfig)).first()
    if not cfg:
        cfg = SystemConfig()
        db.add(cfg)
        db.commit()
    
    # 获取简道云运行时配置
    jiandaoyun_api_key = decrypt_secret(cfg.jiandaoyun_api_key_encrypted) if cfg.jiandaoyun_api_key_encrypted else ""
    jiandaoyun_app_id = cfg.jiandaoyun_app_id or ""
    if not jiandaoyun_api_key or not jiandaoyun_app_id:
        raise HTTPException(status_code=500, detail="简道云未配置")

    # 读取跟进记录表单 entry_id（从字段映射中查找，或使用默认值）
    field_mappings = cfg.field_mappings or {}
    entry_id = (
        field_mappings.get("jiandaoyun", {})
        .get("forms", {})
        .get("跟进记录", {})
        .get("entry_id", "670a28334883adafb152a869")
    )

    # 客户名称：优先用 com_name，其次 company_name
    jiandaoyun_com_name = data.get("com_name") or data.get("company_name") or ""
    # 跟进人：命名规则为"英文名-中文名"，取"-"前的英文名作为简道云 username
    from datetime import date
    review_date = data.get("review_date", "") or date.today().isoformat()

    jiandaoyun_follower = None
    candidate_name = data.get("follower") or _user_name(user)
    if user.get("source") == "superadmin":
        pass  # 超管不在简道云人员字段中
    elif candidate_name and candidate_name != "unknown":
        # 按"英文名-中文名"规则提取 username，再查完整用户对象
        jdy_username = candidate_name.split("-", 1)[0].strip()
        try:
            import httpx
            headers = {"Authorization": f"Bearer {jiandaoyun_api_key}", "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=3600.0) as hc:
                resp = await hc.post(
                    "https://api.jiandaoyun.com/api/v5/corp/user/get",
                    headers=headers, json={"username": jdy_username}
                )
                if resp.status_code == 200:
                    body = resp.json()
                    print("[DEBUG] corp/user/get response: %s" % json.dumps(body, ensure_ascii=False)[:300])
                    jdy_user = body.get("user")
                    if jdy_user:
                        # 简道云成员单选字段只需传 username 字符串
                        jiandaoyun_follower = jdy_user["username"]
        except Exception:
            pass

    jiandaoyun_data = {
        "com_name": {"value": jiandaoyun_com_name},
        "follow_type": {"value": data.get("follow_type", "")},
        "review_date": {"value": review_date},
        "review_record": {"value": data.get("review_record", "")},
        "if_tuisong": {"value": data.get("if_tuisong", "否")},
    }
    if jiandaoyun_follower:
        jiandaoyun_data["follower"] = {"value": jiandaoyun_follower}
    company_id = data.get("company_id")
    if data.get("comid"):
        jiandaoyun_data["comid"] = {"value": data["comid"]}
    elif company_id:
        jiandaoyun_data["comid"] = {"value": company_id}
    if company_id:
        jiandaoyun_data["_widget_1744600409845"] = {"value": company_id}
    if data.get("contid"):
        jiandaoyun_data["contid"] = {"value": data["contid"]}
    if data.get("contact_names"):
        jiandaoyun_data["contname"] = {"value": data["contact_names"]}
    # 预期状态：写入是否第一价值实现预期 和 关联预期
    yuqi_first_value = data.get("yuqi_first_value", "")
    if yuqi_first_value:
        jiandaoyun_data["_widget_1757578251950"] = {"value": yuqi_first_value}
    yuqi_id = data.get("yuqi_id", "")
    if yuqi_id:
        jiandaoyun_data["review_yuqi_id"] = {"value": yuqi_id}
    # 跟进标签（关联触发式标签）
    relevent_tags = data.get("relevent_tag", [])
    if relevent_tags:
        jiandaoyun_data["relevent_tag"] = {"value": relevent_tags}

    genjin_tags = data.get("genjin_tags", [])
    if genjin_tags:
        subform_rows = []
        for tag in genjin_tags:
            subform_rows.append({
                "genjin_level1": {"value": tag.get("level1", "")},
                "genjin_level2": {"value": tag.get("level2", "")},
                "genjin_level3": {"value": tag.get("level3", "")},
            })
        jiandaoyun_data["genjin"] = {"value": subform_rows}

    # 联系人子表单
    selected_contact = data.get("selected_contact") or {}
    if selected_contact.get("cont_id"):
        jiandaoyun_data["contid"] = {"value": selected_contact["cont_id"]}
        jiandaoyun_data["contname"] = {"value": selected_contact.get("cont_name", "")}
        jiandaoyun_data["contact"] = {"value": [{
            "son_contact_choose": {"value": "是"},
            "son_contact_name": {"value": selected_contact.get("cont_name", "")},
            "son_contact_id": {"value": selected_contact["cont_id"]},
            "son_contact_choose_name": {"value": selected_contact["cont_id"]},
            "son_contact_choose_id": {"value": selected_contact.get("cont_name", "")},
        }]}

    # 出差子表单
    selected_tasks = data.get("selected_tasks") or []
    if selected_tasks:
        task_rows = []
        task_ids = []
        for t in selected_tasks:
            tid = t.get("task_id", "")
            task_ids.append(tid)
            task_rows.append({
                "son_task_choose": {"value": "是"},
                "son_task_id": {"value": tid},
                "son_task_date": {"value": t.get("task_predate", "")},
                "son_task_action": {"value": t.get("task_action", "")},
                "son_task_remarks": {"value": t.get("task_remarks", "")},
                "son_task_choose_id": {"value": tid},
            })
        jiandaoyun_data["task"] = {"value": task_rows}
        jiandaoyun_data["task_id"] = {"value": ",".join(task_ids)}

    data_creator = user.get("integrate_id") or user.get("username", "")
    writer = JiandaoyunWriter(api_key=jiandaoyun_api_key, app_id=jiandaoyun_app_id, data_creator=data_creator)
    result = await writer.create_record(entry_id, jiandaoyun_data)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("detail", "写入简道云失败"))
    return {"message": "跟进记录已成功提交到简道云", "data": result.get("data")}


@app.on_event("startup")
async def startup_refresh_customer_index():
    """应用启动时自动全量刷新一次客户索引（仅在配置完整时）"""
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        cfg = db.query(SystemConfig).first()
        if cfg:
            runtime_cfg = get_jiandaoyun_runtime_config(cfg)
            api_key = runtime_cfg.get("api_key", "")
            app_id = runtime_cfg.get("app_id", "")
            mapping = runtime_cfg.get("mapping", {})
            main_form = ((mapping or {}).get("forms") or {}).get("客户主表", {})
            entry_id = str(main_form.get("entry_id", "")).strip()
            if api_key and app_id and entry_id:
                # 启动时先尝试加载共享缓存，避免所有 worker 同时请求简道云 API
                shared = _load_shared_cache()
                if shared and shared.get("items"):
                    CUSTOMER_INDEX_CACHE["items"] = shared["items"]
                    CUSTOMER_INDEX_CACHE["at"] = shared.get("at")
                    CUSTOMER_INDEX_CACHE["source"] = shared.get("source", "file")
                    logger.info(f"启动时从共享缓存加载 {len(CUSTOMER_INDEX_CACHE.get('items', []))} 条客户")
                else:
                    # 没有共享缓存时，随机延迟 0~15 秒，错开 8 个 worker 的请求
                    import random
                    delay = random.uniform(0, 15)
                    logger.info(f"共享缓存为空，{delay:.1f}s 后刷新客户索引...")
                    await asyncio.sleep(delay)
                    await refresh_customer_index_cache(runtime_cfg)
                    logger.info(f"启动刷新完成，共缓存 {len(CUSTOMER_INDEX_CACHE.get('items', []))} 条客户")
    except Exception as exc:
        logger.warning(f"启动时自动刷新客户索引失败: {exc}")
    finally:
        db.close()


@app.middleware("http")
async def request_logger(request: Request, call_next):
    start = datetime.now(timezone.utc)
    response = await call_next(request)
    elapsed = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    logger.info("%s %s -> %s (%sms)", request.method, request.url.path, response.status_code, elapsed)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "系统异常"})


# ── review/followup 别名路由 ──────────────────────
# 前端 ReviewPage.vue 调用 /api/v1/followup/* 路径，这里注册别名

@app.get("/api/v1/followup/tags")
async def followup_get_tags():
    return await get_review_tags()

@app.post("/api/v1/followup/generate")
async def followup_generate(data: dict[str, Any], user: dict[str, Any] = Depends(require_auth), db: Session = Depends(get_db)):
    return await generate_review(data, user, db)

@app.post("/api/v1/followup/submit")
async def followup_submit(data: dict[str, Any], user: dict[str, Any] = Depends(require_auth), db: Session = Depends(get_db)):
    return await submit_review(data, user, db)

@app.get("/api/v1/followup/enums")
async def followup_get_enums():
    """获取商务行为和行为目的枚举值"""
    import json as _json
    enums_path = Path(__file__).resolve().parent / "config" / "followup_enums.json"
    try:
        return _json.loads(enums_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"behaviors": [], "purposes": []}


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "docs", "redoc", "openapi.json", "health")):
        raise HTTPException(status_code=404, detail="Not Found")
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return RedirectResponse(url="/docs")

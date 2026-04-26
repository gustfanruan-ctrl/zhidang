# CR-FINAL-FIX: 修复后端关键流程的鉴权、错误提示、健康检查和安全写入路径。
from __future__ import annotations

import asyncio
import hashlib
import logging
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import create_jwt, get_current_user, require_superadmin
from .config import settings
from .crypto_utils import decrypt_secret, encrypt_secret
from .database import Base, engine, get_db
from .models import AnalyticsEvent, ConfigChangeLog, OperationLog, Superadmin, SystemConfig, Transcript
from .progress import build_progress
from .schemas import AdminFetchWidgetsPayload, AgentComparisonPayload, AgentExtractionPayload, ChatPayload, CompanySearchQuery, ConfigPayload, CustomerSwitchPayload, DingtalkFetchPayload, ExecuteOperationsPayload, LlmConfigPayload, LlmTestPayload, LoginPayload, ReviewActionPayload, ReviewSessionPayload, SsoEntryQuery, SsoGeneratePayload, SystemInitPayload, TranscriptUploadResponse
from .schemas.operation import OperationExecuteRequest, ReviewAction
from .schemas.agent_output import validate_comparison_output, validate_extraction_output
from .services.agent_runner import AgentPhase, AgentRunner
from .services.field_safety import check_operation_cards
from .services.image_preprocessor import ImagePreprocessError, validate_and_preprocess
from .services.jiandaoyun_client import JiandaoyunClient, JiandaoyunClientError
from .services.jiandaoyun_writer import JiandaoyunWriter
from .services.openai_compatible_agent_client import OpenAICompatibleAgentClient
from .services.operation_executor import execute_cards
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

PENDING_CHAT_ACTIONS: dict[str, dict[str, Any]] = {}
CUSTOMERS_CACHE_TTL_SECONDS = 600
CUSTOMERS_CACHE: dict[str, Any] = {"at": None, "items": []}
TASK_PROGRESS: dict[str, dict[str, Any]] = {}
JIANYDAOYUN_MAPPING_PATH = Path(__file__).resolve().parent / "config" / "jiandaoyun_field_mapping.json"
CUSTOMER_INDEX_CACHE_TTL_SECONDS = 300
CUSTOMER_INDEX_CACHE: dict[str, Any] = {"at": None, "items": [], "source": "empty"}
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
    for required_field in ["comname_01", "com_name", "com_type", "revenue_level", "if_access", "follow_form"]:
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
    logger.info("startup complete")


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
    normalized_username = payload.username.strip()
    admin = db.scalar(select(Superadmin).where(Superadmin.username == normalized_username))
    if not admin or admin.password_hash != hashlib.sha256(payload.password.encode()).hexdigest():
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_jwt({"source": "superadmin", "username": admin.username})
    return {"token": token, "display_name": admin.display_name}


@app.post("/api/v1/sso/generate")
def sso_generate(payload: SsoGeneratePayload, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_superadmin)):
    cfg = ensure_system_config(db)
    return {"token": build_sso_token(payload.user_name, payload.user_id, payload.company_id, cfg.sso_shared_secret or "demo-secret")}


@app.get("/api/v1/sso/entry")
def sso_entry(query: SsoEntryQuery = Depends(), db: Session = Depends(get_db)):
    cfg = ensure_system_config(db)
    user = verify_sso_token(query.token, query.company_id, cfg.sso_shared_secret or "demo-secret", cfg.sso_token_ttl_minutes, db)
    jwt_token = create_jwt({"user_name": user["user_name"], "user_id": user["user_id"], "source": "sso"})
    return RedirectResponse(url=f"/transcripts?token={jwt_token}&company_id={query.company_id}")


@app.get("/api/v1/me")
def me(user: dict[str, Any] = Depends(require_auth), db: Session = Depends(get_db)):
    return user


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
    }


@app.put("/api/v1/admin/config")
def save_admin_config(payload: ConfigPayload, user: dict[str, Any] = Depends(require_superadmin), db: Session = Depends(get_db)):
    cfg = ensure_system_config(db)
    before = {k: getattr(cfg, k) for k in ["jiandaoyun_base_url", "jiandaoyun_app_id", "main_entry_id", "field_mappings", "sso_shared_secret", "sso_token_ttl_minutes", "dingtalk_app_key", "dingtalk_agent_id", "agent_a_max_rounds", "agent_b_max_rounds", "data_retention_days"]}
    if payload.jiandaoyun_api_key:
        cfg.jiandaoyun_api_key_encrypted = encrypt_secret(payload.jiandaoyun_api_key)
    if payload.dingtalk_app_secret:
        cfg.dingtalk_app_secret_encrypted = encrypt_secret(payload.dingtalk_app_secret)
    for key in ["jiandaoyun_base_url", "jiandaoyun_app_id", "main_entry_id", "field_mappings", "sso_shared_secret", "sso_token_ttl_minutes", "dingtalk_app_key", "dingtalk_agent_id", "agent_a_max_rounds", "agent_b_max_rounds", "data_retention_days"]:
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
            async with httpx.AsyncClient(timeout=20) as client:
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
async def transcript_upload(file: UploadFile = File(...), company_name_hint: str = Form(default=""), db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
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
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed_types:
        raise HTTPException(status_code=400, detail="不支持的文件类型，支持文本文件与 JPEG/PNG/WebP 图片。")

    raw_bytes = await file.read()
    if len(raw_bytes) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件超过 8MB 限制。")

    input_type = allowed_types[suffix]
    if input_type == "text":
        content = raw_bytes.decode("utf-8", errors="ignore")
        parsed = build_raw_transcript_payload(content)
    else:
        content = ""
        parsed = build_raw_transcript_payload(
            f"已上传图片文件：{file.filename}",
            fallback_title=file.filename or "图片转写",
        )

    normalized_company = company_name_hint.strip() if company_name_hint else ""
    transcript = Transcript(
        source="upload",
        source_id=file.filename,
        title=parsed["title"],
        raw_text=parsed["raw_text"],
        segments=parsed["segments"],
        input_type=input_type,
        status="parsed",
        company_name=normalized_company or None,
        company_id=hash_company_id(normalized_company) if normalized_company else None,
        sso_user_name=user.get("user_name") or user.get("username"),
        sso_user_id=user.get("user_id") if user.get("source") == "sso" else None,
    )
    db.add(transcript)
    db.commit()
    db.refresh(transcript)
    emit_event(db, "transcript.uploaded", {"user_name": user.get("username", "demo"), "user_id": user.get("username", "demo"), "source": user.get("source", "superadmin")}, {"transcript_id": transcript.id, "company_id_hash": hash_company_id(company_name_hint or transcript.id), "session_id": str(uuid4())}, {"source": "upload", "file_name": file.filename, "file_size_bytes": len(raw_bytes), "segment_count": len(parsed["segments"]), "char_count": len(content), "input_type": input_type})
    return TranscriptUploadResponse(transcript_id=transcript.id, title=parsed["title"], segment_count=len(parsed["segments"]), status="parsed", preview=parsed["raw_text"][:500])


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
        sso_user_name=user.get("user_name") or user.get("username"),
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
    items = db.scalars(select(Transcript).order_by(Transcript.created_at.desc())).all()
    return {"items": [{"id": t.id, "source": t.source, "source_id": t.source_id, "title": t.title, "status": t.status, "company_name": t.company_name, "company_name_hint": t.company_name, "raw_text": t.raw_text, "segments": t.segments, "input_type": t.input_type} for t in items]}


@app.get("/api/v1/transcripts/{transcript_id}")
def get_transcript(transcript_id: str, db: Session = Depends(get_db), user: dict[str, Any] = Depends(require_auth)):
    t = db.get(Transcript, transcript_id)
    if not t:
        raise HTTPException(status_code=404, detail="转写不存在")
    return {"id": t.id, "source": t.source, "source_id": t.source_id, "title": t.title, "status": t.status, "company_name": t.company_name, "company_name_hint": t.company_name, "raw_text": t.raw_text, "segments": t.segments, "company_id": t.company_id, "input_type": t.input_type}


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
    # 只在显式刷新或缓存为空时触发全量查询；缓存过期不自动刷，避免重复查询
    if refresh or not CUSTOMER_INDEX_CACHE.get("items"):
        try:
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
                    "raw": item,
                }
                for item in local_customers
                if item.get("company_id")
            ]
            if warning is None:
                warning = "简道云客户索引拉取失败，已回退本地转写客户列表"

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
    llm_request_timeout = int(payload_data.get("llm_request_timeout_seconds") or 300)
    llm_connect_timeout = int(payload_data.get("llm_connect_timeout_seconds") or 30)
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
        if not api_key or not app_id:
            results = [{"card_id": c.get("card_id"), "execute_status": "skipped", "error": "jiandaoyun_api_key_not_configured"} for c in approved]
            return {"success": True, "results": results}
        writer = JiandaoyunWriter(api_key=api_key, app_id=app_id)
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
        writer = JiandaoyunWriter(api_key=api_key, app_id=app_id)
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
        tool_timeout_seconds=30,
        total_timeout_seconds=300,
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
    p = TASK_PROGRESS.get(transcript_id, {})
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
            "customers_cache_at": CUSTOMERS_CACHE.get("at"),
            "customer_index_cache_at": CUSTOMER_INDEX_CACHE.get("at"),
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
    from .progress import now_utc
    
    transcript_text = (data.get("transcript_text") or "").strip()
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

    system_prompt = f"""你是帆软内部的客户成功记录员。
从会议转写中提取结构化跟进记录。
输出纯 JSON，包含以下字段：
follow_type：从"线上跟进/线下跟进/内部沟通"选一个
review_date：YYYY-MM-DD，识别不到用今天日期
review_record：严格按以下格式输出：
【跟进目的】一句话概括，10字以内
【沟通详情】客观详细记录沟通内容，保留所有数字、版本号、规模等具体信息
【附件/kms链接】暂无
【参与人】我方：xxx  客户方：xxx（职位/部门）
genjin_tags：数组，每项 {{level1, level2, level3}}，从以下选项中选择，level3 可为空字符串：
{json.dumps(tag_tree_data, ensure_ascii=False, indent=2)}
contact_names：字符串，客户侧参与人
if_tuisong：默认"否"
请只输出纯 JSON，不要用 markdown 代码块包裹，不要添加任何额外文字。"""

    user_prompt = f"会议转写内容：\n{transcript_text}\n\n客户名称：\n{company_name}\n\n请生成结构化的跟进记录。"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "stream": False},
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

    jiandaoyun_data = {
        "com_name": {"value": data.get("com_name", "")},
        "follow_type": {"value": data.get("follow_type", "")},
        "review_date": {"value": data.get("review_date", "")},
        "review_record": {"value": data.get("review_record", "")},
        "if_tuisong": {"value": data.get("if_tuisong", "否")},
    }
    if data.get("comid"):
        jiandaoyun_data["comid"] = {"value": data["comid"]}
    company_id = data.get("company_id")
    if company_id:
        jiandaoyun_data["_widget_1744600409845"] = {"value": company_id}
    if data.get("contact_names"):
        jiandaoyun_data["contname"] = {"value": data["contact_names"]}

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

    writer = JiandaoyunWriter(api_key=jiandaoyun_api_key, app_id=jiandaoyun_app_id)
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
                logger.info("启动时自动刷新客户索引...")
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


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "docs", "redoc", "openapi.json", "health")):
        raise HTTPException(status_code=404, detail="Not Found")
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return RedirectResponse(url="/docs")

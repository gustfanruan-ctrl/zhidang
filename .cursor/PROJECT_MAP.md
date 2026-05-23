# PROJECT_MAP.md — 智档全项目地图

> 生成时间：2026-05-23  
> 扫描范围：仓库根目录、`backend/app/`、`frontend/src/`（排除 node_modules / .venv / 生成物）  
> 权力地图子模块详见 `.cursor/HANDOFF.md`

---

## 1. 项目顶层结构

| 路径 | 类型 | 说明 | 模块状态 |
|------|------|------|----------|
| `backend/` | 目录 | FastAPI 后端应用 | **已知**（CS 主流程 + 权力地图） |
| `frontend/` | 目录 | Vue 3 + Vite 前端 SPA | **已知** |
| `alembic/` | 目录 | Alembic 数据库迁移脚本 | **已知** |
| `scripts/` | 目录 | 辅助脚本（`init.sql`、GenSpark 测试等） | **已知** |
| `docs/` | 目录 | 文档目录 | **未知**（未展开扫描） |
| `data/` | 目录 | 数据目录 | **未知** |
| `browser_data/` | 目录 | 浏览器数据目录 | **未知** |
| `freellmapi/` | 目录 | 独立 LLM API 相关 | **未知** |
| `migrations/` | 目录 | 迁移相关（与 alembic 并存） | **未知** |
| `project_scripts_docs/` | 目录 | 项目脚本文档 | **未知** |
| `test.har/` | 目录 | HAR 测试数据 | **未知** |
| `.cursor/` | 目录 | Cursor 规则与交接文档 | **已知** |
| `.claude/` | 目录 | Claude Code worktree 副本 | **未知**（非主开发路径） |
| `docker-compose.yml` | 文件 | 三容器编排：postgres + backend + nginx frontend | **已知** |
| `Dockerfile` | 文件 | Python 3.12-slim 后端镜像 | **已知** |
| `requirements.txt` | 文件 | Python 依赖清单 | **已知** |
| `alembic.ini` | 文件 | Alembic 配置 | **已知** |
| `nginx.conf` | 文件 | 前端 Nginx 反向代理配置 | **已知** |
| `main.py`（根） | 文件 | 独立 demo FastAPI（内存态，无 DB） | **已知**（非生产入口） |
| `backend/app/main.py` | 文件 | **生产 FastAPI 入口**（~3400 行，全部 API 路由） | **已知** |
| `CLAUDE.md` | 文件 | Claude Code 开发指南 | **已知** |
| `PROJECT_OVERVIEW.md` | 文件 | 项目总览文档 | **已知** |
| `README.md` | 文件 | 项目简介 | **已知** |
| `产品原型PRD.md` | 文件 | 产品需求文档 | **未知**（未读内容） |
| `埋点设计-PRD.md` | 文件 | 埋点需求文档 | **未知**（未读内容） |
| `本地开发部署文档.txt` | 文件 | 本地开发部署说明 | **未知**（未读内容） |
| `deploy*.py` / `build-remote*.py` 等 | 文件 | 远程部署脚本（约 20+ 个） | **未知**（未逐一读） |
| `cc_*.txt` / `task_*.txt` | 文件 | Claude Code 任务指令存档 | **未知**（历史任务记录） |
| `zhidang.db` | 文件 | 本地 SQLite 数据库文件 | **已知**（开发用） |
| `csm_users.json` / `meiyijia_data.json` | 文件 | 测试/样例数据 JSON | **未知** |

---

## 2. 后端模块清单

### 2.1 `backend/app/` 根级文件

| 文件 | Top 类/函数（≤5） | 职责 | 与权力地图耦合 |
|------|-------------------|------|----------------|
| `main.py` (~3400 行) | `app`, `ensure_system_config`, `run_extraction_task`, `chat_power_map_v2`, `get_current_user` | 全部 API 路由、鉴权、Agent 调度、权力地图 endpoint | **直接耦合**：import `power_map_service`，注册 `/api/v1/power-map/*` 路由 |
| `models.py` | `Superadmin`, `User`, `SystemConfig`, `Transcript`, `FollowupRecord` | 10 张 SQLAlchemy 表定义 | `SystemConfig` 含 `power_map_base_url` 等 4 个权力地图配置字段 |
| `database.py` | `engine`, `SessionLocal`, `get_db`, `Base` | SQLAlchemy 引擎与会话工厂 | 无 |
| `config.py` | `Settings`, `settings` | pydantic-settings 环境变量 | 无 |
| `auth.py` | `create_jwt`, `decode_jwt`, `get_current_user`, `hash_password`, `verify_password` | JWT 签发/校验中间件 | 无 |
| `sso.py` | `build_sso_token`, `verify_sso_token` | SSO HMAC token 签发/校验 + nonce 防重放 | 无 |
| `crypto_utils.py` | `encrypt_secret`, `decrypt_secret`, `_derive_key` | AES-256-GCM 加密（API Key 等） | 解密 `SystemConfig.power_map_auth_token_encrypted` |
| `crypto.py` | — | [死代码] 旧版封装层（232B），所有调用方直接用 crypto_utils | 无 |
| `validators.py` | `sort_by_confidence`, `check_duplicates`, `check_consistency`, `validate_comparison_output` | 操作卡片校验规则 | 无 |
| `writeflow.py` | `merge_and_write`, `build_expectation_row`, `build_scenario_row` | 预期+场景合并写入逻辑 | 无 |
| `progress.py` | `build_progress` | Agent 任务进度结构构建 | 无 |

### 2.2 `backend/app/schemas/`

| 文件 | Top 类/函数（≤5） | 职责 | 与权力地图耦合 |
|------|-------------------|------|----------------|
| `__init__.py` | `BaseAPIModel`, `LoginPayload`, `AgentExtractionPayload`, `ChatPayload`, `PowerMapChatPayload` | 通用请求/响应 Pydantic 模型 | `PowerMapChatPayload`, `PowerMapConfirmPayload`, `PowerMapRelayoutPayload`, `PowerMapPreviewPayload` |
| `agent_output.py` | `ExtractedFact`, `ComparisonOperation`, `validate_extraction_output`, `validate_comparison_output` | Agent 输出校验器 | 无 |
| `followup.py` | `FollowupGenerateRequest`, `FollowupRecord`, `FollowupSubmitRequest`, `GenjinTag` | 跟进记录 Schema + 枚举常量 | 无 |
| `jiandaoyun.py` | `CustomerSummary`, `YuqiRecord`, `ChangjingRecord` | 简道云数据结构 Schema | 无 |
| `operation.py` | `ReviewAction`, `OperationExecuteRequest`, `OperationExecuteResult` | 操作卡片审核/执行 Schema | 无 |

### 2.3 `backend/app/config/`

| 文件 | 职责 | 与权力地图耦合 |
|------|------|----------------|
| `jiandaoyun_field_mapping.json` | 简道云表单→字段→widget 映射 + 安全策略 | 无 |
| `review_tag_tree.json` | 跟进标签树 | 无 |
| `followup_enums.json` | 跟进枚举值 | 无 |

### 2.4 `backend/app/services/`

| 文件 | Top 类/函数（≤5） | 职责 | 与权力地图耦合 |
|------|-------------------|------|----------------|
| `power_map_service.py` (~9800 行) | — | 权力地图核心 | **自身** — 详见 `.cursor/HANDOFF.md` |
| `agent_runner.py` | `AgentRunner`, `AgentPhase`, `AgentResult`, `run` | Agent 多轮工具调用循环引擎 | 无（CS 主流程专用） |
| `tool_registry.py` (~40KB) | `get_tools`, `get_executors`, `FIELD_ALIASES`, `_resolve_field_rule`, `check_operation_cards` | Agent Tool 定义/注册/执行、字段别名/匹配 | 无 |
| `prompts.py` | `EXTRACTION_SYSTEM_PROMPT`, `COMPARISON_SYSTEM_PROMPT`, `POWER_MAP_SYSTEM_PROMPT`, `HARNESS_SYSTEM_PROMPT`, `FOLLOWUP_SYSTEM_PROMPT` | 全部 LLM System Prompt | `POWER_MAP_SYSTEM_PROMPT` + `HARNESS_SYSTEM_PROMPT` 为权力地图专用 |
| `openai_compatible_agent_client.py` | `OpenAICompatibleAgentClient`, `OpenAICompatibleResponse`, `_TextBlock`, `_ToolUseBlock` | OpenAI 兼容 API 客户端（含 SSE 流） | 被 `power_map_service` 的 harness 流调用 |
| `jiandaoyun_client.py` | `JiandaoyunClient`, `JiandaoyunClientError`, `query_data_list`, `create_data`, `update_data` | 简道云 HTTP 客户端（v5→v2 降级） | 无 |
| `jiandaoyun_writer.py` | `JiandaoyunWriter`, `create_record`, `update_record`, `delete_record` | 简道云数据写入封装 | 无 |
| `operation_executor.py` | `execute_cards`, `now_utc`, `_wrap_value` | 审核通过后操作卡片→简道云写入 | 无 |
| `field_safety.py` | `check_operation_cards` | 字段级安全策略校验 | 无 |
| `chat_executor.py` | `build_jiandaoyun_payload`, `build_preview_text`, `get_entry_id` | Chat 对话执行辅助（payload 构建） | 无 |
| `customer_matcher.py` | `MatchResult`, `match_customer` | 客户名称模糊匹配（简道云查询） | 无 |
| `followup_service.py` | `generate_followup_record`, `submit_followup_record`, `FOLLOWUP_SYSTEM_PROMPT` | 跟进记录 LLM 生成 + 简道云提交 | 无 |
| `followup_scraper.py` | `fetch_and_store_followup_records`, `_stringify` | 从简道云抓取跟进记录入库 | 无 |
| `image_preprocessor.py` | `validate_and_preprocess`, `ImagePreprocessError` | 上传图片预处理（缩放/转 JPEG） | 无 |
| `analysis_pipeline.py` | `run_analysis_pipeline` | [死代码] 旧版后台 asyncio 全流程，live main.py 已改为 inline 实现 | 无 |
| `cas_auth.py` | `CasAuthService`, `CasAuthError`, `store_pgt`, `get_bi_session_cookie` | CAS 票据转发，代理访问帆软 BI | **间接耦合**：BI session cookie 供权力地图 BI 数据拉取 |
| `sandbox_infra.py` | `download_bi_resources`, `render_sandbox_html`, `ctx_to_full_getinfo_response`, `verify_manifest` | 权力地图本地 sandbox 渲染基础设施 | **直接耦合**：为 `power_map_service` 提供 sandbox HTML 渲染 |
| `target_form_fallback.py` | `FIELD_TO_FORM`, `patch_target_form` | Agent 输出 target_form 兜底推断 | 无 |

---

## 3. 前端模块清单

### 3.1 入口与基础设施

| 文件 | 行数(约) | 渲染/职责 | API 调用 |
|------|----------|-----------|----------|
| `frontend/index.html` | ~20 | SPA 挂载点 | 无 |
| `frontend/src/main.js` | 68 | Vue 应用入口、路由定义、鉴权守卫 | `GET /api/v1/system/status`, `GET /api/v1/me` |
| `frontend/src/App.vue` | 292 | 根组件：侧边栏导航、客户选择器、主题切换 | `GET /api/v1/me`, `GET/POST /api/v1/customers/*` |
| `frontend/src/api.js` | 88 | Axios 封装（JWT 注入、超时、401 跳转） | 全局拦截器 |
| `frontend/src/styles.css` | — | 全局 CSS 变量主题 | 无 |
| `frontend/vite.config.js` | — | Vite 配置，dev 模式 `/api` 代理到 :8000 | 无 |

### 3.2 页面组件

| 文件 | 行数(约) | 渲染界面 | API 调用 |
|------|----------|----------|----------|
| `pages/TranscriptsPage.vue` | ~1000 | 转写上传、Agent 提取触发、进度显示 | `POST /api/v1/transcript/upload`, `POST /api/v1/transcripts/{id}/analyze`, `GET /api/v1/transcripts`, `GET /api/v1/transcripts/{id}/progress` |
| `pages/ReviewPage.vue` | ~600 | 操作卡片审核 + 跟进记录生成/提交 | `POST /api/v1/operations/review`, `POST /api/v1/operations/execute`, `POST /api/v1/followup/generate`, `POST /api/v1/followup/submit`, `GET /api/v1/followup-records` |
| `pages/ChatPage.vue` | ~400 | 自然语言查询/修改客户档案 | `POST /api/v1/chat` |
| `pages/PowerMapV2Page.vue` | ~250 | **权力地图主页面**（iframe + 聊天面板） | `GET /api/v1/power-map/{id}`, `POST /api/v1/power-map/{id}/chat_v2`, `POST .../commit`, `POST .../discard` |
| `pages/PowerMapPage.vue` | ~1700 | [旧版] 单轮 JSON delta 聊天，无路由指向 | `POST /api/v1/power-map/{id}/chat`, `POST .../confirm`, `POST .../relayout`, `POST .../preview` |
| `pages/ChatV2Panel.vue` | ~400 | 权力地图独立聊天面板（/power-map-chat 路由） | 同 PowerMapV2Page |
| `pages/ConfigPage.vue` | ~350 | 简道云对接配置（superadmin） | `GET/PUT /api/v1/admin/config`, `POST /api/v1/admin/config/test` |
| `pages/LlmPage.vue` | ~300 | LLM 配置（superadmin） | `GET/PUT /api/v1/admin/llm-config`, `POST /api/v1/admin/llm-config/test` |
| `pages/MaintenancePage.vue` | ~250 | 系统健康检查、缓存刷新、数据分析 | `GET /api/v1/admin/maintenance/health`, `POST /api/v1/admin/refresh-cache`, `GET /api/v1/analytics/*` |
| `pages/LoginPage.vue` | ~80 | 登录页 | `POST /api/v1/auth/login` |
| `pages/InitPage.vue` | ~60 | 首次初始化（创建 superadmin） | `POST /api/v1/system/init` |
| `pages/SsoCallbackPage.vue` | ~60 | SSO 回调处理 | `GET /api/v1/sso/entry`, `GET /api/v1/sso/cas-callback` |

### 3.3 API / Store / Service 层

| 文件 | 职责 | API 调用 |
|------|------|----------|
| `api/customer.js` | 客户档案 API 封装 | `GET /api/v1/customers/{id}/profile`, `/yuqi`, `/changjing` |
| `api/operation.js` | 转写 + 操作卡片 API 封装 | `POST /api/v1/transcript/upload`, `/operations/review`, `/operations/execute`, `GET /api/v1/transcripts/*` |
| `api/followup.js` | 跟进记录生成/提交 API | `POST /api/v1/followup/generate`, `/followup/submit`, `GET /api/v1/followup/tags`, `/followup/enums` |
| `api/followup-records.js` | 跟进记录列表/抓取 API | `GET /api/v1/followup-records`, `POST /api/v1/followup-records/fetch` |
| `stores/customer.js` | Pinia 客户状态（缓存/切换/搜索） | `GET /api/v1/customers/list`, `/customers/search`, `POST /api/v1/customers/switch` |
| `stores/powerMapChat.js` | Pinia 权力地图聊天状态（SSE 流管理） | 通过 `services/powerMapChatV2.js` 调用 chat_v2/commit/discard |
| `services/powerMapChatV2.js` | SSE 客户端（fetch + ReadableStream 解析） | `POST /api/v1/power-map/{id}/chat_v2`, `POST .../commit`, `POST .../discard` |

### 3.4 UI 组件

| 目录 | 内容 |
|------|------|
| `components/ui/` | shadcn 风格 UI 原语：Button, Input, Card, Badge, Alert, Skeleton 等（16 个） |
| `components/` | 业务组件：AuthCard, DataTable, NodeCard, StatusBadge, ToastProvider |

---

## 4. API Endpoint 全景

> 全部注册在 `backend/app/main.py`，无独立 Router 模块。

### 4.1 系统 / 鉴权

| 方法 | 路径 | 函数名 | 功能 |
|------|------|--------|------|
| GET | `/health` | `health_check` | 健康检查 |
| GET | `/api/v1/health` | `api_health` | API 健康检查 |
| POST | `/api/v1/system/init` | `system_init` | 首次初始化 superadmin |
| GET | `/api/v1/system/status` | `system_status` | 系统初始化状态 |
| POST | `/api/v1/auth/login` | `auth_login` | 用户名密码登录 |
| GET | `/api/v1/me` | `get_me` | 当前用户信息 |
| POST | `/api/v1/sso/generate` | `sso_generate` | 生成 SSO token |
| GET | `/api/v1/sso/entry` | `sso_entry` | SSO 入口（token 验证 + JWT 签发） |
| GET | `/api/v1/sso/cas-callback` | `sso_cas_callback` | CAS 回调 |
| GET | `/api/v1/sso/cas-pgt-callback` | `sso_cas_pgt_callback` | CAS PGT 回调 |
| GET | `/api/v1/sso/cas-login` | `sso_cas_login` | CAS 登录跳转 |
| GET | `/api/v1/sso/bi-callback` | `sso_bi_callback` | BI 系统 SSO 回调 |

### 4.2 管理 / 配置

| 方法 | 路径 | 函数名 | 功能 |
|------|------|--------|------|
| GET | `/api/v1/admin/config` | `get_admin_config` | 读取简道云配置 |
| PUT | `/api/v1/admin/config` | `update_admin_config` | 更新简道云配置 |
| POST | `/api/v1/admin/config/test` | `test_admin_config` | 测试简道云连接 |
| GET | `/api/v1/admin/llm-config` | `get_llm_config` | 读取 LLM 配置 |
| PUT | `/api/v1/admin/llm-config` | `update_llm_config` | 更新 LLM 配置 |
| POST | `/api/v1/admin/llm-config/test` | `test_llm_config` | 测试 LLM 连接 |
| GET | `/api/v1/admin/maintenance/health` | `maintenance_health` | 系统健康诊断 |
| POST | `/api/v1/admin/refresh-cache` | `refresh_cache` | 刷新客户索引缓存 |
| POST | `/api/v1/admin/jiandaoyun/fetch-widgets` | `fetch_widgets` | 拉取简道云表单 widget 结构 |

### 4.3 转写 / Agent 流水线

| 方法 | 路径 | 函数名 | 功能 |
|------|------|--------|------|
| POST | `/api/v1/transcript/upload` | `upload_transcript` | 上传转写文本/图片 |
| POST | `/api/v1/transcript/dingtalk-fetch` | `dingtalk_fetch` | 从钉钉会议拉取转写 |
| GET | `/api/v1/transcripts` | `list_transcripts` | 转写列表 |
| GET | `/api/v1/transcripts/{transcript_id}` | `get_transcript` | 转写详情 |
| POST | `/api/v1/transcripts/{transcript_id}/analyze` | `analyze_transcript` | 触发 Agent 提取+比对 |
| GET | `/api/v1/transcripts/{transcript_id}/progress` | `get_transcript_progress` | Agent 任务进度 |
| POST | `/api/v1/agent/extraction/task` | `agent_extraction_task` | Agent-A 提取任务 |
| POST | `/api/v1/agent/comparison/task` | `agent_comparison_task` | Agent-B 比对任务 |

### 4.4 操作卡片 / 审核 / 执行

| 方法 | 路径 | 函数名 | 功能 |
|------|------|--------|------|
| POST | `/api/v1/operations/review-action` | `review_action` | 单条操作卡片审核动作（埋点） |
| POST | `/api/v1/operations/review-session` | `review_session` | 审核会话统计（埋点） |
| POST | `/api/v1/operations/add` | `add_operation` | 手动添加操作卡片 |
| POST | `/api/v1/operations/review` | `review_operations` | 批量审核操作卡片 |
| POST | `/api/v1/operations/execute` | `execute_operations` | 执行已审核操作卡片→简道云 |
| GET | `/api/v1/operations/{transcript_id}/status` | `operation_status` | 操作执行状态 |

### 4.5 客户 / 简道云数据

| 方法 | 路径 | 函数名 | 功能 |
|------|------|--------|------|
| GET | `/api/v1/customers/list` | `customers_list` | 客户列表（缓存索引） |
| GET | `/api/v1/companies/search` | `companies_search` | 公司搜索 |
| GET | `/api/v1/customers/search` | `customers_search` | 客户关键词搜索 |
| GET | `/api/v1/customers/{company_id}/profile` | `customer_profile` | 客户主表档案 |
| GET | `/api/v1/customers/{company_id}/yuqi` | `customer_yuqi` | 客户预期列表 |
| GET | `/api/v1/customers/{company_id}/changjing` | `customer_changjing` | 客户场景列表 |
| POST | `/api/v1/customers/switch` | `customer_switch` | 切换当前客户（埋点） |

### 4.6 对话 / 跟进记录

| 方法 | 路径 | 函数名 | 功能 |
|------|------|--------|------|
| POST | `/api/v1/chat` | `chat` | 自然语言查询/修改客户档案 |
| GET | `/api/v1/followup-records` | `list_followup_records` | 跟进记录列表 |
| GET | `/api/v1/followup-records/{record_id}` | `get_followup_record` | 跟进记录详情 |
| POST | `/api/v1/followup-records/fetch` | `fetch_followup_records` | 从简道云抓取跟进记录 |
| GET | `/api/v1/review/tags` | `review_tags` | 跟进标签树 |
| POST | `/api/v1/review/generate` | `review_generate` | LLM 生成跟进记录 |
| POST | `/api/v1/review/submit` | `api/v1/review/submit` | 提交跟进记录到简道云 |
| GET | `/api/v1/followup/tags` | `followup_tags` | 跟进标签（US-2） |
| POST | `/api/v1/followup/generate` | `followup_generate` | 生成跟进记录（US-2） |
| POST | `/api/v1/followup/submit` | `followup_submit` | 提交跟进记录（US-2） |
| GET | `/api/v1/followup/enums` | `followup_enums` | 跟进枚举值 |

### 4.7 权力地图

| 方法 | 路径 | 函数名 | 功能 |
|------|------|--------|------|
| GET | `/api/v1/power-map/{company_id}` | `get_power_map` | 获取权力地图数据 |
| GET | `/api/v1/power-map/{company_id}/bi-com-id` | `get_bi_com_id` | 获取 BI com_id |
| POST | `/api/v1/power-map/{company_id}/chat` | `chat_power_map` | 单轮 JSON delta 聊天 |
| POST | `/api/v1/power-map/{company_id}/confirm` | `confirm_power_map` | 确认变更写回 BI |
| POST | `/api/v1/power-map/{company_id}/relayout` | `relayout_power_map` | 重新布局 |
| POST | `/api/v1/power-map/{company_id}/preview` | `preview_power_map` | 预览布局（dry-run） |
| GET | `/api/v1/power-map/{company_id}/harness-stream` | `harness_stream` | Harness SSE 流 |
| POST | `/api/v1/power-map/{company_id}/chat_v2` | `chat_power_map_v2` | 多轮工具调用聊天（SSE） |
| GET | `/api/v1/power-map/debug/dump_ctx` | `dump_ctx` | 调试：dump MergeContext |
| POST | `/api/v1/power-map/{company_id}/commit` | `commit_power_map` | 提交 harness session 变更 |
| POST | `/api/v1/power-map/{company_id}/discard` | `discard_power_map` | 丢弃 harness session 变更 |

### 4.8 Sandbox / BI 代理 / 静态

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/power_map/sandbox` | Sandbox HTML 渲染 |
| GET | `/api/power_map/sandbox-proxy` | Sandbox 资源代理 |
| GET | `/sandbox/render` | Sandbox 渲染入口 |
| POST | `/sandbox/download` | 下载 BI 资源到本地 sandbox |
| GET | `/WebReport/decision/url/power_map/getInfo` | BI getInfo 代理 |
| POST | `/WebReport/decision/url/power_map/upInfo` | BI upInfo 代理 |
| GET | `/WebReport/decision/url/power_map/update_expect` | BI 更新预期代理 |
| GET | `/WebReport/decision/url/power_map/update_scene` | BI 更新场景代理 |
| GET | `/WebReport/decision/url/power_map/judge_phone` | BI 手机判断代理 |
| POST | `/WebReport/decision/url/power_map/upFile` | BI 文件上传代理 |
| GET | `/WebReport/decision/url/power_map/get_archive_jdy_id` | BI 简道云 ID 代理 |
| GET | `/WebReport/decision/url/power_map/position_tree_combo` | BI 职位树代理 |
| GET | `/static/sandbox/watermark/{name:path}` | Sandbox 水印静态资源 |

### 4.9 分析 / 调试 / SPA

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/v1/analytics/business/overview` | 业务分析概览 |
| GET | `/api/v1/analytics/system/accuracy` | 系统准确率分析 |
| GET | `/api/v1/analytics/system/prompt-compare` | Prompt 对比分析 |
| GET | `/api/v1/analytics/export` | 分析数据导出 |
| GET | `/api/v1/debug/customers` | 调试：客户索引 |
| POST | `/test/seed_session` | 测试：种子 session |
| GET | `/` | SPA 入口 |
| GET | `/{full_path:path}` | SPA fallback |

---

## 5. 数据模型清单

### 5.1 SQLAlchemy 模型（`backend/app/models.py`）

| 类名 | 字段数 | 引用者 |
|------|--------|--------|
| `TimestampMixin` | 2 | 所有表 mixin |
| `Superadmin` | 4 | `auth.py`, `main.py` |
| `User` | 7 | `auth.py`, `main.py`, `cas_auth.py` |
| `SystemConfig` | 28 | `main.py`（全局配置读写） |
| `Transcript` | 14 | `main.py` |
| `FollowupRecord` | 16 | `main.py`, `followup_scraper.py` |
| `SsoNonceUsed` | 2 | `sso.py` |
| `OperationLog` | 8 | `main.py`, `chat_executor.py` |
| `ConfigChangeLog` | 4 | `main.py` |
| `AnalyticsEvent` | 13 | `main.py` |
| `OperationCardLog` | 12 | `operation_executor.py`, `main.py` |

### 5.2 Pydantic 模型 — `schemas/__init__.py`

| 类名 | 字段数 | 引用者 |
|------|--------|--------|
| `BaseAPIModel` | 0（基类） | 所有 schema |
| `SystemInitPayload` | 3 | `main.py` |
| `LoginPayload` | 2 | `main.py` |
| `AdminConfigPayload` | 16 | `main.py` |
| `LlmConfigPayload` | 11 | `main.py` |
| `AgentExtractionPayload` | 10 | `main.py` |
| `ComparisonTaskPayload` | 4 | `main.py` |
| `ReviewActionPayload` | 8 | `main.py` |
| `ReviewSessionPayload` | 8 | `main.py` |
| `ChatPayload` | 4 | `main.py` |
| `ExecuteOperationsPayload` | 4 | `main.py` |
| `PowerMapChatPayload` | 4 | `main.py` |
| `PowerMapConfirmPayload` | 2 | `main.py` |
| `PowerMapRelayoutPayload` | 3 | `main.py` |
| `PowerMapPreviewPayload` | 2 | `main.py` |
| 其他（Transcript/Dingtalk/Customer 等） | 2-5 各 | `main.py` |

### 5.3 Pydantic 模型 — 其他 schema 文件

| 类名 | 文件 | 字段数 | 引用者 |
|------|------|--------|--------|
| `ExtractedFact` | `agent_output.py` | 7 | `agent_output.py`, `main.py` |
| `ComparisonOperation` | `agent_output.py` | — | `agent_output.py` |
| `FollowupGenerateRequest` | `followup.py` | 7 | `followup_service.py`, `main.py` |
| `FollowupRecord` | `followup.py` | 10 | `followup_service.py` |
| `FollowupSubmitRequest` | `followup.py` | 13 | `followup_service.py`, `main.py` |
| `CustomerSummary` | `jiandaoyun.py` | 7 | 无直接 import（文档/备用） |
| `YuqiRecord` | `jiandaoyun.py` | 7 | 无直接 import |
| `ChangjingRecord` | `jiandaoyun.py` | 6 | 无直接 import |
| `ReviewAction` | `operation.py` | 4 | 无直接 import |
| `OperationExecuteRequest` | `operation.py` | 3 | 无直接 import |

### 5.4 Dataclass / 服务内模型

| 类名 | 文件 | 字段数 | 引用者 |
|------|------|--------|--------|
| `AgentResult` | `agent_runner.py` | 7 | `agent_runner.py`, `main.py` |
| `AgentPhase` | `agent_runner.py` | 2（Enum） | `agent_runner.py` |
| `MatchResult` | `customer_matcher.py` | 2 | `customer_matcher.py`, `tool_registry.py` |
| `OpenAICompatibleResponse` | `openai_compatible_agent_client.py` | 2 | `openai_compatible_agent_client.py`, `power_map_service.py` |
| `_TextBlock` / `_ToolUseBlock` / `_ReasoningBlock` | `openai_compatible_agent_client.py` | 2-4 各 | 内部 |
| `PowerNode` 等 | `power_map_service.py` | — | 详见 HANDOFF.md |
| `Settings` | `config.py` | 10 | `config.py`, `database.py`, `auth.py` |

---

## 6. 已解决的不确定区（2026-05-23 审计结论）

### Q1 — `crypto.py` vs `crypto_utils.py`
**结论：可安全删除。** `crypto.py`（232B）是向后兼容的薄封装，仅一行 `from .crypto_utils import decrypt_secret, encrypt_secret`。无任何代码主动 import 它，所有调用方直接 `from .crypto_utils import`。标记为死代码。

### Q2 — `freellmapi/` 目录
**结论：历史遗留独立项目。** 这是名为「FreeLLMAPI」的独立项目（Node.js + React），功能是聚合 14 个免费 LLM 提供商的 OpenAI-compatible 统一端点。与智档项目无关，已在 `.gitignore` 中排除。

### Q3 — `migrations/` vs `alembic/`
**结论：仅 `alembic/` 在使用。** 不存在独立的 `migrations/` 目录。`alembic/versions/` 下有 4 个迁移文件（0001_initial → 0004_add_users），`alembic.ini` 在根目录。没有其他迁移系统。

### Q4 — 跟进记录双路径
**结论：已统一为 `/api/v1/followup-records`。** 旧版双路径（`/review/generate` + `/review/submit` 和 `/followup/generate` + `/followup/submit`）仅存在于 `main.py.bak` 中，已废弃。当前 live `main.py`（3410 行）只保留 `/api/v1/followup-records` 和 `/api/v1/followup-records/{id}`，前端 `ReviewPage.vue` 调用新路径。

### Q5 — `analysis_pipeline.py` 的触发入口
**结论：死代码。** 唯一调用方是 `main.py.bak` 中的 `POST /api/v1/transcripts/{id}/analyze`（异步 `create_task` 启动）。当前 live `main.py` 的 analyze 路由已改为 inline 实现，`analysis_pipeline.py` 在 live 代码中无任何 import 引用。

### Q6 — `OPERATION_CARD_STORE` 生命周期
**结论：仍在内存 dict，容器重启丢失。** `main.py` L261 `OPERATION_CARD_STORE: dict[str, list[dict[str, Any]]] = {}`。启动时从 DB 加载最近完成的卡片（L633-648），但审核中的操作卡片未持久化。`OperationCardLog` 表已存在用于审计记录。`main.py.bak` 中注释称「By design for short review cycles」。**风险**：容器重启丢失审核中的卡片。

### Q7 — 生产部署脚本
**结论：`deploy-47-v2.py`（目标 47.98.102.197）为当前生产部署脚本。** 各脚本分工：

| 脚本 | 目标 IP | 用途 |
|------|---------|------|
| `deploy-47-v2.py` | 47.98.102.197 | **当前生产**，上传文件清单最全 |
| `deploy-47.py` | 47.98.102.197 | 旧版生产 |
| `deploy.py` | 43.252.230.38 | 另一台机器（TOC Maker） |
| `deploy-quick.py` | 47.98.102.197 | 快速重建容器（仅 docker compose） |
| `deploy_cas.py` | — | CAS 配置专用 |
| `deploy-commit.py` | — | 提交+推送快捷脚本 |

实际生产部署当前走手动流程：`scp → docker cp → docker compose restart`。

### Q8 — `PowerMapPage.vue` vs `PowerMapV2Page.vue`
**结论：旧版可安全删除。** `PowerMapV2Page.vue`（~250 行）通过路由 `/power-map` 提供生产服务。`PowerMapPage.vue`（~1700 行）无任何路由指向，已从菜单移除，仅作历史保留。

### Q9 — CAS auth 与 BI 拉取链路
**结论：CAS session cookie 为主路径，Bearer token 为 fallback。** 完整链路（3 个调用点均通过 `cas_auth_service.get_bi_session_cookie()`）：
1. `_fetch_from_external` L8488
2. `_capture_power_map_screenshot` L3009
3. `_capture_sandbox_screenshot` L8559

同时存在独立 auth token 降级路径（L8503）：CAS cookie 失败时使用 `Bearer {api_cfg['auth_token']}`。

### Q10 — `backend/app/api/` 目录
**结论：空目录，预留未启用。** `backend/app/api/v1/` 目录为空，无任何文件。所有路由仍在 `main.py` 单体中（~3400 行），此为预留给未来路由拆分的占位目录。

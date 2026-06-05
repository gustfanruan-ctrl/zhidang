# 智档（ZhiDang）项目总览

> 面向新加入工程师的快速理解文档。基于代码实际内容生成，不编造。

---

## 1. 项目目的和核心功能

**智档** 是一个**客户成功（Customer Success）自动化平台**。核心目标：把 CSM（客户成功经理）的会议转写文本/截图，通过 LLM 自动提取为结构化的「客户预期」和「业务场景」，经人工审核后写入简道云客户档案。

### 核心功能模块

| 模块 | 能力 | 页面 |
|------|------|------|
| 转写上传与解析 | 上传会议文本/截图，LLM 提取客户预期 + 业务场景 | `/transcripts` |
| 双 Agent 流水线 | Agent-A 提取 → Agent-B 比对已有档案 → 生成操作卡片 | 后台 |
| 人工审核 | 审核 Agent 生成的操作卡片（确认/编辑/删除） | `/review` |
| 简道云写入 | 审核通过后自动写入简道云（新增/更新客户档案） | 后台 |
| 对话查询 | 自然语言查询/修改简道云客户档案 | `/chat` |
| 跟进记录生成 | 从会议内容自动生成结构化跟进记录并提交简道云 | `/review` |
| 系统配置 | 简道云对接配置、LLM 配置、SSO | `/config`, `/llm` |
| 维护与数据 | 系统健康检查、数据清理、分析埋点 | `/maintenance` |

---

## 2. 技术栈和依赖

### 后端
| 技术 | 用途 |
|------|------|
| **Python 3.12** | 运行语言 |
| **FastAPI** | Web 框架，提供 REST API |
| **SQLAlchemy 2.x** | ORM，声明式模型 |
| **PostgreSQL 16** | 主数据库（docker-compose 部署） |
| **Alembic** | 数据库迁移管理 |
| **Pydantic v2** | 请求/响应 Schema 校验 |
| **httpx** | 异步 HTTP 客户端（调用简道云 API + LLM API） |
| **anthropic** | Anthropic Claude SDK（Agent 主 LLM） |
| **cryptography** | AES-256-GCM 加密（保护 API Key 等敏感配置） |
| **PyJWT** | JWT 鉴权 |
| **Pillow** | 上传图片预处理（缩放/格式转换） |
| **python-multipart** | 文件上传支持 |
| **pydantic-settings** | 环境变量配置管理 |

### 前端
| 技术 | 用途 |
|------|------|
| **Vue 3.5** (Composition API) | 前端框架 |
| **Vite 6** | 构建工具，开发热更新 |
| **Vue Router 4** | SPA 路由 |
| **Pinia 2** | 状态管理（客户上下文） |
| **Axios** | HTTP 请求（拦截器处理 JWT 鉴权） |

### 外部依赖
- **简道云（Jiandaoyun）**：客户档案存储（客户主表、预期表、场景表、跟进记录表）
- **LLM**：Anthropic Claude + OpenAI-compatible（DashScope Qwen），通过 `/chat/completions` 端点
- **Docker / Docker Compose**：全栈一键部署

---

## 3. 目录结构和职责

```
zhidang/
├── backend/                    # 后端代码（FastAPI）
│   ├── app/                    # 应用核心
│   │   ├── main.py             # ⭐ FastAPI 主入口（3400+ 行，全部 API 路由、业务逻辑）
│   │   ├── models.py           # SQLAlchemy 数据模型（7 张表）
│   │   ├── database.py         # 数据库引擎和会话工厂
│   │   ├── config.py           # pydantic-settings 环境变量配置
│   │   ├── auth.py             # JWT 签发/校验中间件
│   │   ├── sso.py              # SSO token 签发/校验（HMAC-SHA256）
│   │   ├── crypto_utils.py     # AES-256-GCM 加密工具（API Key 等）[crypto.py 为死代码薄封装]
│   │   ├── validators.py       # 输入校验
│   │   ├── writeflow.py        # 合并写入逻辑（预期+场景合并）
│   │   ├── progress.py         # 任务进度工具
│   │   ├── config/             # 配置文件（JSON 种子数据）
│   │   │   ├── jiandaoyun_field_mapping.json  # ⭐ 简道云字段映射（表单→widget→安全策略）
│   │   │   └── review_tag_tree.json            # 跟进标签树
│   │   ├── schemas/            # Pydantic Schema（请求/响应模型）
│   │   │   ├── __init__.py     # 通用 Schema + Payload
│   │   │   ├── agent_output.py # Agent 输出校验器
│   │   │   ├── followup.py     # 跟进记录 Schema
│   │   │   ├── jiandaoyun.py   # 简道云数据 Schema
│   │   │   └── operation.py    # 操作卡片 Schema
│   │   └── services/           # ⭐ 核心业务服务
│   │       ├── agent_runner.py          # Agent 执行引擎（工具调用循环）
│   │       ├── tool_registry.py         # Tool 注册表（25KB，核心代码）
│   │       ├── prompts.py              # LLM System Prompt（提取+比对+跟进）
│   │       ├── openai_compatible_agent_client.py  # OpenAI 兼容 API 客户端
│   │       ├── jiandaoyun_client.py     # 简道云 API 客户端（v5/v2 双版本降级）
│   │       ├── jiandaoyun_reader.py     # 简道云数据读取服务
│   │       ├── jiandaoyun_writer.py     # 简道云数据写入服务
│   │       ├── operation_executor.py    # 操作卡片执行器（写入简道云）
│   │       ├── field_safety.py          # 字段安全校验（禁止写入/值限制）
│   │       ├── chat_executor.py         # Chat 对话执行器
│   │       ├── customer_matcher.py      # 客户名称模糊匹配
│   │       ├── followup_service.py      # 跟进记录生成服务
│   │       ├── image_preprocessor.py    # 图片预处理（缩放/转 JPEG）
│   │       └── analysis_pipeline.py      # [死代码] 旧版后台全流程，live main.py 已改为 inline 实现
│   └── output/                 # 输出目录
├── frontend/                   # 前端代码（Vue 3 + Vite）
│   ├── src/
│   │   ├── main.js             # Vue 应用入口、路由定义
│   │   ├── App.vue             # ⭐ 根组件（导航、客户选择、鉴权）
│   │   ├── api.js              # Axios 封装（超时/鉴权/错误处理）
│   │   ├── styles.css          # 全局样式（CSS 变量主题）
│   │   ├── pages/
│   │   │   ├── TranscriptsPage.vue  # ⭐ 转写上传页（30KB，核心页面）
│   │   │   ├── ReviewPage.vue       # ⭐ 审核页（20KB，操作卡片审核）
│   │   │   ├── ChatPage.vue         # 对话页
│   │   │   ├── ConfigPage.vue       # 简道云配置页
│   │   │   ├── LlmPage.vue          # LLM 配置页
│   │   │   ├── MaintenancePage.vue  # 维护页
│   │   │   ├── LoginPage.vue        # 登录页
│   │   │   ├── InitPage.vue         # 首次初始化页
│   │   │   └── SsoCallbackPage.vue  # SSO 回调
│   │   ├── stores/
│   │   │   └── customer.js          # 客户状态管理（Pinia）
│   │   └── api/
│   │       ├── customer.js          # 客户 API 封装
│   │       └── operation.js         # 操作 API 封装
│   ├── vite.config.js          # Vite 配置（代理到后端 :8000）
│   └── package.json            # 前端依赖
├── alembic/                    # 数据库迁移
│   ├── env.py                  # Alembic 环境配置
│   └── versions/               # 迁移版本文件
├── scripts/                    # 辅助脚本
│   ├── init.sql                # 数据库初始化 SQL
│   ├── genspark_chat.py        # GenSpark 对话脚本
│   ├── run_genspark_once.py    # 单次运行脚本
│   └── test_genspark_chat.py   # 测试脚本
├── main.py                     # 独立版 demo（单文件 FastAPI，不依赖数据库）
├── docker-compose.yml          # 三容器编排（postgres + backend + frontend）
├── Dockerfile                  # Python 3.12-slim 镜像
├── requirements.txt            # Python 依赖
├── alembic.ini                 # Alembic 配置
├── .env.example                # 环境变量模板
├── 产品原型PRD.md              # 产品需求文档
├── 埋点设计-PRD.md             # 埋点需求文档
├── 本地开发部署文档.txt        # 本地开发指南
└── README.md                   # 项目简介
```

### 各层职责速记

| 层级 | 目录 | 职责 |
|------|------|------|
| **路由层** | `backend/app/main.py` | 51 个 API 端点，请求分发、鉴权注入 |
| **Schema 层** | `backend/app/schemas/` | 请求校验、类型定义 |
| **服务层** | `backend/app/services/` | 业务逻辑：Agent 运行、简道云读写、字段安全 |
| **数据层** | `backend/app/models.py` | 7 张 SQLAlchemy 模型 |
| **配置层** | `backend/app/config/` | JSON 种子数据（字段映射、标签树） |
| **前端页** | `frontend/src/pages/` | 9 个 Vue SFC 页面 |

---

## 4. 核心数据流（用户请求完整链路）

### 主链路：转写上传 → 提取 → 比对 → 审核 → 写入

```
┌──────────┐     ┌──────────────────────────────────────────────────┐     ┌──────────┐
│  用户     │     │                  智档 后端                        │     │ 简道云    │
│  (前端)   │     │                                                  │     │          │
└────┬─────┘     └─────────────────────┬────────────────────────────┘     └────┬─────┘
     │                                 │                                       │
     │  ① POST /api/v1/transcript/upload                                     │
     │  (文本/图片/混合)                  │                                       │
     │ ─────────────────────────────>  │                                       │
     │                                 │ ② 图片预处理 (image_preprocessor)       │
     │                                 │    └─ base64解码→缩放→转JPEG            │
     │                                 │                                       │
     │                                 │ ③ 存入 Transcript 表 (models.py)       │
     │  ←─── transcript_id ────────── │                                       │
     │                                 │                                       │
     │  ④ POST /api/v1/agent/extraction/task                                 │
     │  { transcript_id }              │                                       │
     │ ─────────────────────────────>  │                                       │
     │                                 │ ⑤ Agent-A 执行 (agent_runner.py)      │
     │                                 │    ├─ System Prompt: prompts.py       │
     │                                 │    ├─ LLM: Anthropic / OpenAI compat  │
     │                                 │    ├─ Tools: tool_registry.py         │
     │                                 │    └─ 输出: facts[] (预期+场景)        │
     │  ←─── extraction_result ────── │                                       │
     │                                 │                                       │
     │  ⑥ POST /api/v1/agent/comparison/task                                 │
     │  { extraction_result, company_id }                                     │
     │ ─────────────────────────────>  │                                       │
     │                                 │ ⑦ 拉取简道云已有数据                   │ ───> │
     │                                 │    jiandaoyun_reader.py                │       │
     │                                 │    └─ 客户主表 + 预期表 + 场景表       │ <─── │
     │                                 │                                       │
     │                                 │ ⑧ Agent-B / 规则引擎比对              │
     │                                 │    ├─ 语义相似度匹配                   │
     │                                 │    ├─ 生成操作卡片 (create/update/skip)│
     │                                 │    └─ 字段安全校验 (field_safety.py)   │
     │  ←─── operation_cards[] ────── │                                       │
     │                                 │                                       │
     │  ⑨ 用户在 ReviewPage 审核       │                                       │
     │  POST /api/v1/operations/review │                                       │
     │  (approve / reject / edit)      │                                       │
     │ ─────────────────────────────>  │                                       │
     │                                 │                                       │
     │  ⑩ POST /api/v1/operations/execute                                    │
     │  { transcript_id, card_ids[] }  │                                       │
     │ ─────────────────────────────>  │                                       │
     │                                 │ ⑪ operation_executor.py              │ ───> │
     │                                 │    └─ JiandaoyunWriter.create/update  │ 简道云  │
     │                                 │                                       │ 写入    │
     │  ←─── execute_results ──────── │                                       │ <─── │
```

### Chat 对话链路（自然语言查询/修改）

```
用户输入 ─→ POST /api/v1/chat ─→ chat_executor.py
                                    ├─ 判断意图（查询 vs 修改）
                                    ├─ 查询模式 → JiandaoyunReader → 返回数据
                                    └─ 修改模式 → 预览 → 用户确认 → JiandaoyunWriter
```

### 跟进记录生成链路

```
用户输入文本 ─→ POST /api/v1/followup/generate → LLM 生成结构化记录 → 前端预览
          ─→ POST /api/v1/followup/submit   → JiandaoyunWriter → 简道云「跟进记录」表

（旧版 /api/v1/review/generate + /review/submit 已废弃，仅存在于 main.py.bak）
```

---

## 5. 关键业务逻辑文件索引

### 核心逻辑（按重要性排序）

| 文件 | 行数 | 核心职责 | 什么场景改这里 |
|------|------|---------|--------------|
| `backend/app/main.py` | 3411 | 全部 API 路由、鉴权、转录管理、客户索引、会话管理 | 加新 API、改业务流程、改鉴权逻辑 |
| `backend/app/services/tool_registry.py` | 589 | Agent Tools 定义/注册/执行、字段别名/匹配/安全规则 | 加新 Tool、改字段映射逻辑、改 Agent 行为 |
| `backend/app/services/agent_runner.py` | 267 | Agent 工具调用循环引擎（多轮 LLM + Tool 交互） | 改 Agent 运行机制、加超时策略 |
| `backend/app/services/prompts.py` | 257 | LLM System Prompt（提取/比对/跟进） | 改 AI 提取质量、改 Prompt 策略 |
| `backend/app/models.py` | 147 | 7 张数据表模型定义 | 加新表、改字段 |
| `backend/app/services/jiandaoyun_client.py` | 197 | 简道云 HTTP API 客户端（v5/v2 双版本降级） | 简道云 API 改动、加新接口 |
| `backend/app/services/operation_executor.py` | 138 | 操作卡片执行器（审核通过后写入简道云） | 改写入逻辑、改 lookup 关联 |
| `backend/app/services/field_safety.py` | — | 字段安全策略校验（禁止字段/值限制） | 改安全策略 |
| `backend/app/config/jiandaoyun_field_mapping.json` | 151 | 简道云表单→字段→widget 映射 + 安全配置 | 改表单结构、加新字段映射 |

### 前端核心

| 文件 | 行数 | 核心职责 |
|------|------|---------|
| `frontend/src/pages/TranscriptsPage.vue` | ~1000 | 转写上传、Agent 提取触发、进度显示 |
| `frontend/src/pages/ReviewPage.vue` | ~600 | 操作卡片审核（确认/编辑/删除）、跟进记录生成 |
| `frontend/src/App.vue` | 296 | 根组件：鉴权、导航、客户选择器 |
| `frontend/src/stores/customer.js` | 91 | Pinia 客户状态（缓存/切换/搜索） |

---

## 6. 常见开发任务该改哪些文件

### 场景 A：「Agent 提取质量不好，要改 Prompt」
→ 改 `backend/app/services/prompts.py`
→ 如果涉及字段规则变更，同步改 `backend/app/services/tool_registry.py` 中的 FIELD_ALIASES 和字段解析逻辑
→ 如果改 system_prompt 常量后有数据库默认值同步需求，改 `backend/app/models.py` 中 SystemConfig 的 default 值

### 场景 B：「简道云表单结构变了（加了新字段）」
→ 改 `backend/app/config/jiandaoyun_field_mapping.json`（加新字段的 widget 映射 + safety 策略）
→ 改 `backend/app/services/tool_registry.py`（FIELD_ALIASES 加中文别名映射）
→ 如果涉及新的 Tool 定义，在 `tool_registry.py` 的 `get_tools()` 函数中注册

### 场景 C：「要加一个新的前端页面」
→ 在 `frontend/src/pages/` 新建 `.vue` 文件
→ 在 `frontend/src/main.js` 中注册路由
→ 在 `frontend/src/App.vue` 的导航中添加 `<RouterLink>`

### 场景 D：「要加一个新的 API 端点」
→ 在 `backend/app/main.py` 中添加 `@app.post/get(...)` 路由函数
→ 如果请求体复杂，在 `backend/app/schemas/__init__.py` 中定义 Pydantic 模型
→ 如果需要新的数据表，在 `backend/app/models.py` 中定义模型

### 场景 E：「LLM 提供商要从 DashScope 换成别的」
→ 改 `backend/app/main.py` 中 `get_system_llm_config()` 的默认 provider 和 base_url
→ 确认 LLM 客户端兼容性：如果也是 OpenAI-compatible，走 `openai_compatible_agent_client.py`；否则改 `agent_runner.py` 的 `llm_client` 构建逻辑

### 场景 F：「数据库要加一张新表」
→ 在 `backend/app/models.py` 中定义 SQLAlchemy 模型
→ 运行 Alembic 自动生成迁移：`alembic revision --autogenerate -m "add xxx"`
→ 在 `backend/app/main.py` 中 import 新模型

### 场景 G：「审核页面的操作卡片规则要改」
→ 写规则改 `backend/app/services/tool_registry.py`（Tool 定义 + 字段映射）
→ 安全规则改 `backend/app/services/field_safety.py` 或 `jiandaoyun_field_mapping.json`
→ 前端展示改 `frontend/src/pages/ReviewPage.vue`

---

## 7. 已知的坑和注意事项

### 架构层面的坑

1. **`main.py` 是巨型文件（3400+ 行）**
   所有 API 路由和业务逻辑都在一个文件里。改动时要小心不要意外影响其他路由。后续应考虑拆分为 Router 模块（`backend/app/api/` 目录已预留）。

2. **存在两个 `main.py`**
   - **根目录 `main.py`**：独立 demo 版本，用 `STATE` 字典做内存存储，不依赖 PostgreSQL。仅用于快速演示。
   - **`backend/app/main.py`**：正式版本，连接数据库。Docker 启动的是这个。
   - 修改功能时注意区分二者，避免改了 demo 以为改了正式版。

3. **简道云 API v5/v2 双版本降级**
   `jiandaoyun_client.py` 对每个操作都先尝试 v5 API，失败后降级到 v2。降级时注意错误信息的传递（见 `query_data_list` 中 `'v5_response' in locals()` 的特判逻辑）。

4. **内存中的操作卡片存储**
   审核阶段的操作卡片存在 `OPERATION_CARD_STORE`（Python 字典），重启即丢失。这是设计选择（审核流程短），但如果需要持久化，应考虑入库。

5. **加密密钥的派生逻辑**
   `crypto_utils.py` 中加密密钥从 `ZHIDANG_SECRET_KEY` 环境变量或 `JWT_SECRET` 派生。如果更换 JWT_SECRET，所有已加密的配置项（API Key）将无法解密，需要重新配置。

### 技术细节的坑

6. **Anthropic SDK 的 Try-Catch**
   `main.py` 开头 `try: from anthropic import AsyncAnthropic` 可能静默失败。如果 Anthropic SDK 安装失败，整个 Agent 流水线会回退到 fallback 模式。

7. **客户 ID 哈希**
   客户 `company_id` 通过 SHA-256 哈希存储（`hash_company_id()` 函数），对外不可逆。如果需要在外部直接关联原始 company_id，注意这个推导链。

8. **前端超时配置**
   前端有独立的超时配置系统（`api.js` 中的 `getApiTimeout()` / `getBackendTimeoutConfig()`），存在 localStorage 中。首次使用默认 30s。如果 Agent 执行超过此时间，前端会报超时，需要在前端调整。

9. **SSO Nonce 防重放**
   SSO 使用了数据库表 `sso_nonce_used` 防重放（而非内存集合），每次 SSO 登录会写入一条 nonce 记录。长期运行需要清理过期 nonce。

10. **客户索引缓存**
    `CUSTOMER_INDEX_CACHE` 和 `CUSTOMERS_CACHE` 有 TTL 过期机制。启动时会自动刷一次。如果简道云新增了客户但前端看不到，可能是缓存未过期，等待 5-10 分钟或重启服务。

11. **字段映射的 alias 解析优先级**
    `tool_registry.py` 中的 `_resolve_field_rule()` 有四层回退：直接匹配 → 标准化匹配 → 别名表匹配 → 语义关键字推断。加新字段时确保别名表覆盖，否则可能落入语义推断产生错误映射。

12. **操作卡的 `customer_id` / `data_id` 缺失**
    写入简道云时，`operation_executor.py` 需要 lookup widget 和 customer_id 来建立关联。如果 Agent 未正确提供这些，写入会失败（`execute_status: "failed"`）。

### 开发环境注意

13. **本地开发推荐用 SQLite**
    修改 `.env` 中 `DATABASE_URL=sqlite:///./zhidang.db`，无需启动 PostgreSQL。部分功能（如 GIN 索引）仅 PostgreSQL 支持。

14. **前端代理配置**
    开发时前端请求通过 `vite.config.js` 的 proxy 转发到 `http://127.0.0.1:8000`。确保后端在 8000 端口运行。

15. **Docker 模式下前端是 dev server**
    `docker-compose.yml` 中前端命令是 `npm run dev -- --host 0.0.0.0`（开发模式），生产部署应改为 `npm run build` + nginx 静态文件服务。

16. **死代码清单（2026-05-23 审计确认）**
    - `backend/app/crypto.py`（232B）：薄封装，无任何 import 引用，所有调用方直接用 `crypto_utils`
    - `backend/app/services/analysis_pipeline.py`：旧版后台全流程，live main.py 已改为 inline 实现，无引用
    - `frontend/src/pages/PowerMapPage.vue`（~1700 行）：旧版权力地图页面，无路由指向，已被 V2 替代
    - `backend/app/api/`：空目录，预留给未来路由拆分

17. **跟进记录端点已统一**
    当前 live 代码只有 `/api/v1/followup-records` 和 `/api/v1/followup-records/{id}`。旧版 `/api/v1/review/generate`、`/api/v1/review/submit`、`/api/v1/followup/generate`、`/api/v1/followup/submit` 仅存在于 `main.py.bak` 中，已废弃。

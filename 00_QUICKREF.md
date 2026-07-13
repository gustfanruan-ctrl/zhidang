# 00_QUICKREF

## 项目速览
- 栈：Python + FastAPI + SQLAlchemy + Vue 3 + Vite
- 主业务：转写/跟进记录 -> LLM 提取/比对 -> 审核 -> 写回简道云
- 主入口：`backend/app/main.py`
- 核心高频路由：`chat` / `review` / `transcripts` / `power-map`

## 文件体量
- 最大后端：`backend/app/services/power_map_service.py` (8484)
- 最大静态页：`backend/app/static/sandbox/powerMap_v3.13.html` (6675)
- 最大主业务：`backend/app/main.py` (3450)
- 前端核心页：`frontend/src/pages/PowerMapPage.vue` (1774), `TranscriptsPage.vue` (1330), `ReviewPage.vue` (803)

## 近 3 个月高频改动
1. `backend/app/main.py` (49)
2. `frontend/src/pages/ReviewPage.vue` (24)
3. `frontend/src/pages/TranscriptsPage.vue` (20)
4. `frontend/src/App.vue` (11)
5. `backend/app/services/followup_service.py` (9)
6. `backend/app/services/prompts.py` (7)
7. `backend/app/models.py` (7)
8. `frontend/src/stores/customer.js` (7)
9. `Dockerfile` (6)
10. `backend/app/config/jiandaoyun_field_mapping.json` (6)

## Top 10 文件速览

### `backend/app/main.py`
- 角色：API 路由、认证、审核、转写、跟进、统计、静态页兜底的总入口
- 开头：集中导入 `auth/config/models/schemas/services`
- 关键函数：`ensure_system_config`, `sync_prompt_defaults`, `transcript_dingtalk_fetch`, `review_action`, `operations_review`, `analytics_export`, `spa_fallback`

### `frontend/src/pages/ReviewPage.vue`
- 角色：操作卡/跟进生成与审核界面
- 开头：页面头部、步骤条、模板设置按钮
- 关键状态：`steps`, `reviewData`, `selectedContactId`, `taskList`, `currentStep`

### `frontend/src/pages/TranscriptsPage.vue`
- 角色：转写/跟进双模式入口页
- 开头：模式切换、刷新跟进记录按钮
- 关键状态：`sourceMode`, `selectedIds`, `fetchingFollowup`, `isSuperadmin`

### `frontend/src/App.vue`
- 角色：全局壳、侧边栏、客户选择、路由框架
- 开头：侧边栏品牌区 + 客户搜索
- 关键状态：`isAuthed`, `isSuperadmin`, `customerStore`, `selectedCustomerId`

### `backend/app/services/followup_service.py`
- 角色：跟进记录生成/提交服务
- 开头：US-2 说明、四段式 system prompt 相关注释
- 关键函数：`now_utc`, `_parse_date`, `_build_review_record_text`, `_build_genjin_subform_rows`, `FollowupService`

### `backend/app/services/prompts.py`
- 角色：LLM system prompts 集中定义
- 开头：`EXTRACTION_SYSTEM_PROMPT`
- 关注点：提取规则、字段语义、预期输出约束

### `backend/app/models.py`
- 角色：SQLAlchemy 表结构
- 开头：`TimestampMixin`, `Superadmin`, `User`
- 关键表：`SystemConfig`, `Transcript`, `FollowupRecord`, `SsoNonceUsed`, `OperationLog`, `ConfigChangeLog`, `AnalyticsEvent`, `OperationCardLog`

### `frontend/src/stores/customer.js`
- 角色：客户缓存、归一化、搜索/列表读写
- 开头：缓存 key、当前客户读写、归一化逻辑
- 关键函数：`cacheKey`, `readStoredCustomer`, `normalizeCustomer`, `normalizeCustomers`

### `Dockerfile`
- 角色：后端镜像构建、系统依赖、Playwright 安装
- 关注点：`python:3.12-slim`、阿里源、`playwright install chromium`

### `backend/app/config/jiandaoyun_field_mapping.json`
- 角色：简道云表单/字段映射与安全配置
- 关注点：`forms`, `entry_id`, `match_field`, `display_fields`, `field_mapping`, `safety`

## 导航建议
- 先看：`backend/app/main.py`
- 再看：`backend/app/services/followup_service.py`
- 然后看：`frontend/src/pages/TranscriptsPage.vue` 和 `ReviewPage.vue`
- 高优先路由：`chat`、`review`、`transcripts`、`power-map`
- 配置联动：`backend/app/config/jiandaoyun_field_mapping.json` + `backend/app/services/tool_registry.py` + `backend/app/services/prompts.py`

## 排障留痕
- 统一埋点：`backend/app/services/tracing.py`
- 入口 trace：`new_trace("ext")` / `new_trace("rvw")` / `new_trace("rwj")`
- 事件日志：`emit(...)` / `emit_llm(...)`
- Power Map 可回放态：`_new_session_id()` + `_store_session()` + `_get_session()`
- 关键检索词：`trace_id`、`session_id`、`TASK_PROGRESS`、`OPERATION_CARD_STORE`、`emit_event`

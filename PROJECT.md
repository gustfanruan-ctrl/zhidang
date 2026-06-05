最后更新：2026-05-25 by Claude Code session
当前主分支：**`feature/followup-records-pipeline`**（未合并到 master，包含所有最新修复）

# 智档 (ZhiDang) 项目手册

## 1. 项目定位

- **一句话**：智档是面向 CSM（客户成功经理）的自动化平台，从会议转写/跟进记录中提取结构化信息，比对简道云已有数据后生成操作卡片，人工审核后写回简道云。
- **核心业务问题**：CSM 拜访客户后需要手动整理纪要、更新简道云中的客户预期和场景表，耗时且易遗漏。系统用 LLM 自动完成提取→比对→写回。
- **当前阶段**：MVP 向生产过渡。核心链路跑通，有真实用户（Gust 张小洋），正在做流程效率优化和兜底能力补全。

## 2. 业务背景与领域概念

- **简道云 (Jiandaoyun)**：帆软旗下的零代码平台，客户关系数据存在其中。三张核心表：客户主表、预期表、场景表。
- **客户主表**：存储公司基本信息（公司名、行业、营收层级等）。每行有 JDY `_id` 和 CRM `com_id`（UUID 格式，如 `c191f13c-3e24-4921-974e-b33022d8adbe`）。
- **预期表**：客户中长期目标/方向。关键字段：预期简述、预期详情、预期状态、是否第一价值实现预期。通过 `relation` 字段关联客户主表。
- **场景表**：预期下的具体落地动作。关键字段：场景标题、解决什么问题、怎样解决。通过 `_widget_1737335801798` 关联客户主表，通过 `_widget_1751435602563` 关联预期表。
- **跟进记录**：CSM 拜访后填写的结构化记录，也存入简道云。有独立的跟进标签体系 + 联系人/出差子表单。
- **操作卡片 (Operation Card)**：Agent 比对新旧数据后生成的 create/update/skip 指令，经人工审核后执行。
- **权力地图**：客户内部决策链和组织架构的可视化图谱，来自帆软 BI（FineReport）。通过 Playwright 无头浏览器截图 + LLM vision 进行自然语言修改。
- **Harness**：权力地图 Agent 的提示词 + 工具调度框架。`_HARNESS_TOOLS_OPENAI` 定义了 20+ 个工具（create_node, create_edge, place_node, resize_container 等）。
- **BI / 帆软**：`crm.finereporthelp.com`，提供权力地图的 iframe 版和沙箱 HTML 版。
- **跟进标签 (genjin tag)**：三级标签体系（level1/level2/level3），如"使用推进→常态化跟进→(空)"。每个 level1+level2 组合对应一个 JDY 标签定义 ID（`genjin_id`）。

## 3. 系统架构总览

### 整体分层

```
前端 (Vue3 + Vite + Tailwind)    → 单页应用，Nginx 托管
后端 (FastAPI + SQLAlchemy)      → 主逻辑单体，~3700 行 main.py
Agent 层 (Anthropic SDK / httpx) → 桥接 LLM 网关 it-ai.fineres.com
外部依赖                           → 简道云 API / 帆软 BI / PostgreSQL
```

### 关键数据流

**流 A：转写→分析→审核→执行**
1. 用户上传转写文件（txt/md/srt）→ Transcript 记录入库
2. 后台 `asyncio.create_task` 启动 `run_analysis_pipeline`
3. Agent-A 提取事实 → Agent-B 比对简道云已有数据 → 生成操作卡片
4. 卡片存 `OPERATION_CARD_STORE`（内存 dict）+ 写 DB `agent_b_result`
5. 用户在审核页批准/拒绝 → `operations_review` 更新内存+DB
6. 用户提交 → `execute_cards` 逐卡调用简道云 API 写入

**流 B：权力地图对话**
1. 前端加载 BI iframe URL → 后端拉取帆软数据构建 MergeContext
2. Playwright 对本地沙箱截图 → 图片 + 用户指令发给 LLM
3. LLM 在 tool-calling 循环中操作节点/边/容器
4. 每轮生成新截图供 LLM 观察 → 收敛后用户确认提交 → 写回帆软

**流 C：跟进记录**
1. 用户在 ReviewPage 手动或 LLM 辅助填写跟进记录表单
2. POST `/api/v1/followup/submit` → 构建 JDY 格式 payload
3. 同步写入跟进标签子表单 + 联系人子表单 + 出差子表单

### 关键外部依赖

| 依赖 | 作用 |
|------|------|
| PostgreSQL | 唯一数据库，存用户/Transcript/FollowupRecord/SystemConfig |
| 简道云 API v5 | 客户数据查询、预期/场景/跟进记录读写 |
| 帆软 BI API | 权力地图数据拉取和提交 |
| `it-ai.fineres.com` | LLM 网关，代理到 Claude/DeepSeek 等模型 |
| 帆软 CRM API | 客户联系人/任务数据（com_id 查询） |

## 4. 代码地图

### 后端核心

| 模块 | 职责 | 关键文件 |
|------|------|---------|
| 主路由 | 51 个 API 端点 + 认证 + 业务逻辑，是系统入口 | `backend/app/main.py`（3680 行，过大） |
| 权力地图 Agent | vision-LLM 多轮工具调用循环，20+ 工具 | `backend/app/services/power_map_service.py`（9794 行！） |
| 提取/比对 Agent | Anthropic-format 工具调用循环，文本为主的提取+比对 | `backend/app/services/agent_runner.py`（286 行） |
| 工具注册 | 工具定义、参数字段别名、LLM 比对引擎 | `backend/app/services/tool_registry.py`（922 行） |
| 分析管道 | 后台提取→比对全流程编排 | `backend/app/services/analysis_pipeline.py`（202 行） |
| 操作执行 | 审核通过后逐卡写入简道云 | `backend/app/services/operation_executor.py`（138 行） |
| 简道云客户端 | HTTP 封装，v5→v2 降级 | `backend/app/services/jiandaoyun_client.py` |
| 简道云写入器 | create/update/delete + 子表单追加 | `backend/app/services/jiandaoyun_writer.py` |
| 字段安全 | 字段级写保护、值约束校验 | `backend/app/services/field_safety.py` |
| LLM 客户端 | OpenAI 兼容协议封装（httpx 连接池复用） | `backend/app/services/openai_compatible_agent_client.py` |
| 沙箱基础设施 | BI HTML 下载、宿主、渲染 | `backend/app/services/sandbox_infra.py` |
| 效率评审 | 权力地图收敛后异步评审落盘 | `backend/app/services/efficiency_review.py` |
| Prompts | 所有 LLM 系统提示词 | `backend/app/services/prompts.py` |
| Tracing | 结构化性能打点（contextvars 传播 trace_id） | `backend/app/services/tracing.py` |

### 前端核心

| 页面 | 路由 | 职责 |
|------|------|------|
| 转写管理 | `/transcripts` | 上传、分析触发、操作卡片审核、提交执行 |
| 跟进记录 | `/review` | 会议→跟进记录生成 + 提交到简道云 |
| 权力地图 | `/power-map` | BI iframe + 沙箱预览 + 对话面板 |
| 对话 | `/chat` | NL 查询/修改客户预期和场景 |
| 简道云配置 | `/config` | 超管配置简道云 API/字段映射 |
| LLM 配置 | `/llm` | 超管配置 LLM 网关/模型 |
| 维护 | `/maintenance` | 系统状态 + 调试工具 |
| 用户管理 | `/admin/users` | 超管增删改用户 |

### 配置与种子数据

| 文件 | 内容 |
|------|------|
| `backend/app/config/jiandaoyun_field_mapping.json` | 表单→字段→widget 映射 + lookup_customer 配置 |
| `backend/app/config/review_tag_tree.json` | 跟进标签三级树 + JDY 标签 ID 映射 |

## 5. 关键设计决策与理由（共 12 条）

### 决策 1：OPERATION_CARD_STORE 用内存 dict 而非 DB 做审核状态主存储
- **备选**：全走 DB，审核操作直接 UPDATE agent_b_result
- **理由**：审核是高频短时操作（几分钟内完成），内存 dict 零延迟。DB 仅做重启恢复的备份。
- **影响**：`operations_review` 同时写内存和 DB；`_reload_cards_on_startup` 在启动时从 DB 恢复；重启会丢失 OPERATION_CARD_STORE，但 DB 兜底。
- **注意**：前端审核状态（`reviewState` Map）是另一层客户端状态，需在 `loadCardsFromTranscript` 中从 DB 恢复。

### 决策 2：company_id 在分析阶段写死为 "demo" 兜底 → 后续改为执行阶段覆盖
- **备选**：分析时用 company_name 做 match_customer 搜索 JDY
- **理由**：match_customer 依赖公司名精确匹配，精准度不足。改为执行阶段让用户显式选择公司，后端覆盖 card.customer_id。
- **影响**：`analysis_pipeline.py:105`（`company_id or ""`）、`main.py` execute_operations 的 company_id 覆盖逻辑、前端审核卡片公司选择器。

### 决策 3：Docker 镜像未 bind mount 后端源码，导致 SFTP 部署不生效
- **备选**：加 bind mount 或每次 rebuild 镜像
- **理由**：历史原因——最初用 `build: .` 方式，后续运维发现更新文件需要 `docker cp` 两步操作（宿主机→容器）。
- **影响**：本地 `deploy-feature.py` 的 SFTP 上传**无效**，必须追加 `docker cp` 进容器。未来建议在 `docker-compose.yml` 给 `backend` 加源码 bind mount。

### 决策 4：权力地图使用 Playwright 截图 + vision LLM，而非直接操作 BI iframe
- **备选**：直接在前端 iframe 里注入 JS 操作 DOM
- **理由**：帆软 BI 的 iframe 跨域、DOM 结构不透明、需要 eval 解析。截图+vision 更通用、更稳定。
- **影响**：`power_map_service.py` 的 `_run_llm_tool_loop` 全程依赖沙箱截图；沙箱 HTML 文件需预先下载（`download_bi_resources`），且容器重启后需重新挂载。

### 决策 5：tool_result 采用规则压缩而非 LLM 摘要
- **备选**：对长 tool_result 用 LLM 摘要后传给下一轮
- **理由**：零延迟、零幻觉、结构化数据足够。效率评审子系统独立异步运行，不阻塞主流程。
- **影响**：`power_map_service.py` 中的 `_TOOL_RESULT_COMPRESS_KEEP_FIELDS` 定义了保留字段；`efficiency_review.py` 仅做评审落盘，不自动更新 prompt。

### 决策 6：跟进记录写简道云时，comid 用 CRM UUID 而非 JDY _id
- **备选**：用 JDY `_id` 作为 comid
- **理由**：简道云跟进表中的 `comid` 字段存储的是 CRM 系统的 com_id（UUID 36 位），不是 JDY 内部 `_id`。真实人工填写的数据已验证此格式。
- **影响**：前端 `ReviewPage.vue` 必须传 `customerStore.currentCustomer.com_id`；跟进标签需要 `genjin_id` 映射表。

### 决策 7：Chat 确认流程依赖 LLM 调用 write 工具设置 pending_write
- **备选**：解析 LLM 文本输出，自动识别确认意图
- **理由**：可靠性和可审计性——只有 LLM 真正调用了工具才会产生可执行的 pending action
- **问题**：LLM 有时只生成确认话术但不调工具，导致 `needs_confirmation` 为 false。已在 prompts 中加强约束（规则 1.5）。
- **影响**：`main.py` 的 chat 端点 + `agent_runner.py` 的 `pending_write` 机制

### 决策 8：前端审核状态双轨制——客户端 `reviewState` Map + DB `agent_b_result.review_status`
- **备选**：纯客户端状态（不持久化），或纯 DB（每次操作查 DB）
- **理由**：客户端状态保证立即响应，DB 兜底防止刷新丢失。`loadCardsFromTranscript` 从 DB 恢复 `reviewState`。
- **影响**：`TranscriptsPage.vue` 的 `reviewState` reactive Map + `loadCardsFromTranscript` 中的 hydration 逻辑
- **注意**：去掉 auto-approve fallback 后，pending 卡显式展示"待审核"黄标，不再默认全部通过。

### 决策 9：幂等覆盖 target_form 和 lookup_widget，而非仅在变更时更新
- **备选**：仅当 `target_form` 与原始值不同时才更新
- **理由**：`switchCardType` 会修改前端本地 `card.target_form`，使 override 检测失效。始终发送 override 更简单可靠。
- **影响**：`main.py` execute_operations 中 `card_overrides` 处理逻辑；前端 `submitCards` 始终包含 `cardOverrides[cardId]`

### 决策 10：跟进标签采用静态映射表而非动态查询 JDY 标签定义
- **备选**：每次提交时实时查询 JDY 标签数据
- **理由**：JDY 标签定义变化频率极低（月度级别），静态映射表零延迟，维护成本低
- **影响**：`review_tag_tree.json` 的 `tag_id` 字段需与 JDY 同步；新增标签时需更新映射表

### 决策 11：效率评审（efficiency_review）只做落盘不做自动 prompt 更新
- **备选**：评审结果自动注入 `HARNESS_SYSTEM_PROMPT`
- **理由**：自动更新风险太高，可能引入破坏性变更。人工每周 review + 手动更新更安全。
- **影响**：`efficiency_review.py` 仅输出 JSON 文件；采样策略为 max_rounds_hit 必审、≤8 轮不审、其他 20% 随机

### 决策 12：`_wrap_value(customer_id)` 直接传字符串而非数组
- **备选**：`{"value": ["id"]}` 数组格式
- **理由**：JDY v5 API 对 lookup 字段接受字符串值（linkdata → `{"value": "id"}`）。跟进记录已验证此格式。
- **影响**：`operation_executor.py` line 90 + `main.py` followup_submit

## 6. 已知约束与边界

- **性能约束**：权力地图 LLM 调用 50-103s/次（~55 tokens/s），非流式。沙箱截图 1-3s/轮。50 轮硬上限后强制退出。
- **协议约束**：`it-ai.fineres.com` 网关对 Anthropic-format tool_calls 到 OpenAI-format 的翻译偶有 id 字段丢失，已用 `_local_ids` 本地化映射（见 `openai_compatible_agent_client.py:406-408`）。
- **业务约束**：简道云 API key 必须 AES-256-GCM 加密存储；跟进记录 follower 取 `integrate_id`（简道云 username）；超管用户 `source="superadmin"` 不走 CSM 过滤。
- **前端超时**：Agent 任务默认 300s，存储在 localStorage 的 `zhidang_timeout` 中。
- **容器化约束**：前端 dist 是 bind mount，**不能** `rm -rf + mkdir` 重建目录，否则 inode 断裂 nginx 返回 500。只能原地覆盖文件。
- **DeepSeek R1 约束**：reasoning 模型破坏多轮工具调用，只能用 `deepseek-chat` 或 `v4-pro`。

## 7. 工具集与扩展规范

### Chat 工具（客户档案维护）

| 工具 | Agent 阶段 | 说明 |
|------|-----------|------|
| query_customer_records | COMPARISON | 查询客户在预期表/场景表的已有记录 |
| create_customer_record | COMPARISON | 新增一条预期/场景记录（需确认） |
| update_customer_record | COMPARISON | 更新已有记录（需确认） |
| delete_customer_record | COMPARISON | 删除记录（需确认） |

定义在 `tool_registry.py` 的 `get_chat_tools()`。

### 权力地图 (Harness) 工具

当前 ~20 个工具，按类型分组：

| 类别 | 工具 | 说明 |
|------|------|------|
| 节点 CRUD | create_node, update_node, delete_node | person/department 类型 |
| 边 CRUD | create_edge, update_edge, delete_edge | 汇报关系 |
| 容器 | resize_container, create_container, delete_container | 部门容器 |
| 布局 | place_node, auto_layout, fit_container_to_children | 坐标调整 |
| 查询 | get_graph_state | 返回当前全量节点/边 JSON |
| 状态 | save_state | 保存当前图状态（已废弃） |

工具定义在 `power_map_service.py` 顶部的 `_HARNESS_TOOLS_OPENAI` 列表中。`save_state` 已在 chat_power_map_v2 中过滤掉。

### 分析管道工具

| 工具 | 阶段 | 说明 |
|------|------|------|
| extract_customer_facts | EXTRACTION | Agent-A 提取结构化事实 |
| fetch_customer_profile | COMPARISON | Agent-B 读取客户档案 |
| compare_and_generate_operations | COMPARISON | 比对并生成操作卡片 |

定义在 `tool_registry.py` 的 `_REGISTRY`。

### 新增工具规范

- 工具名用 snake_case，描述用中文
- input_schema 的 required 字段必须包含 `company_id`
- 写操作工具必须在 `write_tools` 集合中注册
- 新增后同步更新 `prompts.py` 中对应 Agent 的 system prompt
- 禁止在工具 executor 里直接调 LLM（会导致循环依赖）
- 禁止工具 executor 执行实际的 JDY 写入（只返回 preview，等待用户确认）
- 跟进记录标签工具需包含 `tag_id` 映射

## 8. 已知坑与历史教训

### 坑 1：容器 `build: .` 导致 SFTP 上传源码不生效
- **现象**：SFTP 上传 `main.py` 到宿主机 `docker compose restart` 后容器仍跑旧代码
- **原因**：源码 COPY 进镜像而非 bind mount，restart 不会 reload 源码
- **绕坑**：必须 `docker cp /opt/zhidang/... zhidang-backend-1:/app/...` 两步操作
- **位置**：`deploy-feature.py` 和所有手动部署流程

### 坑 2：`fetch_customers_for_user` 生成的 company_id 是 SHA-256 hash
- **现象**：非超管用户看到的客户列表 company_id 可能是 64 位 hash 而非 24 位 JDY `_id`
- **原因**：该函数从 Transcript 表聚合客户，`company_id or hash_company_id(name)` 兜底
- **绕坑**：审核卡片加公司选择器手动覆盖；前端传 `company_id` 到 execute API
- **位置**：`main.py:349-363`；`TranscriptsPage.vue` 审核卡片区

### 坑 3：`switchCardType` 同时改了 `card.target_form` 导致 override 检测失效
- **现象**：前端切了场景→预期，但后端执行时仍用旧的 target_form 写入错误的简道云表
- **原因**：`switchCardType` 同步更新了 `card.target_form`，使前端 `item._targetForm !== card.target_form` 恒为 false，`cardOverrides` 永远为空
- **绕坑**：改为始终发送 `cardOverrides[cardId] = { target_form: item._targetForm }`，不做 diff
- **位置**：`TranscriptsPage.vue` submitCards

### 坑 4：手动新增卡片 `change_items` 为空时 field_updates 不生效
- **现象**：手动加的卡片编辑字段后提交，JDY 记录无数据
- **原因**：原代码 `if change_items:` 守卫导致空列表时跳过字段追加
- **绕坑**：改为 `change_items = card.get("change_items") or []`，空列表也可从 field_updates 追加新字段
- **位置**：`main.py` execute_operations 的 field_updates 处理

### 坑 5：`exec_fetch_profile` 在 company_id 为 hash 时跳过 match_customer 回退
- **现象**：company_id 是 SHA-256 hash（truthy），`if not company_id` 守卫直接跳过，走 JDY 查询必然失败
- **原因**：hash 不是有效 JDY `_id`，`query_single_data` 失败后才到 except 块走 match_customer
- **绕坑**：`analysis_pipeline.py:105` 改为 `company_id or ""`（空字符串走回退）
- **位置**：`tool_registry.py:293-317`；`analysis_pipeline.py:105`

### 坑 6：沙箱 HTML 文件不在镜像中，容器启动后首次访问才下载
- **现象**：权力地图报"沙箱截图失败"或 503 Service Unavailable
- **原因**：沙箱 HTML 依赖 `download_bi_resources` 从帆软动态下载，镜像里没有
- **绕坑**：首次使用前触发 POST /sandbox/download（需超管）；加 Docker volume 持久化 `./backend/static/sandbox`
- **位置**：`sandbox_infra.py`；`docker-compose.yml` backend volumes；`main.py` /sandbox/render

### 坑 7：前端 dist bind mount 不能用 rm -rf 更新
- **现象**：`rm -rf frontend/dist && mkdir frontend/dist` 后 nginx 返回 500
- **原因**：bind mount 绑定的是 inode，删除目录后容器仍持有旧 inode，新 mkdir 创建新 inode
- **绕坑**：只覆盖文件，不删目录；或 `docker compose restart frontend` 重新挂载
- **位置**：`docker-compose.yml` frontend.volumes；所有部署脚本

### 坑 8：DeepSeek R1 reasoning 模型破坏多轮工具调用
- **现象**：Agent 工具调用循环只走一轮就停止，或 reasoning_content 导致上下文膨胀
- **原因**：R1 的 reasoning 输出被当成普通 content block 传给下一轮，干扰工具调用格式
- **绕坑**：仅使用 `deepseek-chat`、`deepseek-v4-pro`，禁用 reasoning 模型
- **位置**：`openai_compatible_agent_client.py` 的 `_ReasoningBlock` 处理

### 坑 9：多 tool_call 在某些 LLM 网关会被翻译错乱
- **现象**：Anthropic SDK 的多 tool_call 经过 OpenAI 兼容网关后 tool_call_id 丢失或错位
- **原因**：`it-ai.fineres.com` 网关对 tool_call 的翻译有时不保留 Anthropic 的 tool_use id
- **绕坑**：用 `_local_ids` 本地化映射（`bedrock_idx → call_<uuid16>`），不依赖网关传回的 id
- **位置**：`openai_compatible_agent_client.py:406-408` messages_create_with_history_stream

### 坑 10：简道云客户索引缓存跨进程不同步
- **现象**：一个 worker 进程刷新了缓存，另一个进程还是旧数据
- **原因**：`CUSTOMER_INDEX_CACHE` 是进程内存 dict，uvicorn 多 worker 不共享
- **绕坑**：共享文件缓存 `_load_shared_cache` / `_save_shared_cache` 作为进程间同步
- **位置**：`main.py` 的 `CUSTOMER_INDEX_CACHE` 相关函数

### 坑 11：`db.scalars()` 与 `db.execute()` 返回值类型不同
- **现象**：`db.scalars(select(User))` 返回的是 `ScalarResult`（不是 list），`.all()` 才得到 list
- **绕坑**：单条用 `db.scalar(select(User).where(...))`、`db.scalar_one_or_none(select(User).where(...))`
- **位置**：散落各处，特别是 admin users 相关代码

### 坑 12：确认按钮灰色的根因不是前端渲染问题，而是后端 `needs_confirmation` 为 false
- **现象**：用户看到确认话术但按钮灰色，以为是前端 bug
- **原因**：LLM 生成确认文本但不调 write 工具 → `pending_write` 为 None → 返回 `needs_confirmation: false`
- **绕坑**：prompts 新增规则 1.5 强制调工具；前端打字"确认"也可触发 confirm 流程
- **位置**：`prompts.py` CHAT_SYSTEM_PROMPT；`ChatPage.vue` send 函数

### 坑 13：`PENDING_CHAT_ACTIONS` 在服务器重启后丢失
- **现象**：用户点击确认执行时提示"操作已过期"
- **原因**：`PENDING_CHAT_ACTIONS` 是进程内存 dict，重启清空
- **绕坑**：暂无持久化方案。当前对话周期短（几分钟），重启概率低。修复建议：存 DB 或 Redis。
- **位置**：`main.py:214` `PENDING_CHAT_ACTIONS = {}`

## 9. 不要做的事

- **不要**给 `_run_llm_tool_loop` 加新的 break/return 条件，统一走现有的 3 个收敛出口（natural_converge / consecutive_no_tool / max_rounds_hit）
- **不要**直接修改 `accumulated_messages`，所有写入必须通过 LLM tool-call 结果的正常流程
- **不要**引入新的 Python 依赖，优先复用 `httpx` / `asyncio` / `paramiko`
- **不要**在 tools 的 executor 里调 LLM
- **不要**用 `db.scalars().first()` 取单条，用 `db.scalar()` 或 `db.scalar_one_or_none()`
- **不要**跳过 `operation_executor` 直接调 `JiandaoyunClient` 写数据——会绕过 `field_safety`
- **不要**在 Dockerfile 里硬编码镜像源（aliyun apt/pip），容器 rebuild 环境不同会失败
- **不要**`rm -rf` 后 `mkdir` 更新 dist 目录
- **不要**用流式调用带 tools 的 Anthropic 请求——`it-ai.fineres.com` 网关对流式+tool 的支持不稳定
- **不要**把 `PENDING_CHAT_ACTIONS` 的内容暴露到前端，只传 `needs_confirmation: bool`

## 10. 测试与验证手段

### 主要测试入口
```bash
# 本地跑后端
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

# 前端开发
cd frontend && npm run dev   # Vite :5173, 代理 /api → :8000

# 全栈 Docker
docker compose up --build
```

### 关键调试端点
- `GET /api/v1/system/status` — 系统初始化状态
- `GET /api/v1/debug/customers` — 客户缓存状态 + 简道云配置检查
- `POST /sandbox/download` — 手动触发沙箱资源下载（需超管）
- `GET /sandbox/render?session_id=xxx` — 测试沙箱渲染

### 日志位置
- 容器日志：`docker logs zhidang-backend-1`
- 性能打点：grep `_metric` 过滤 JSON 事件
- 效率评审：grep `[DEBUG-J review]` 或 `efficiency_reviews/YYYY-MM-DD/*.json`
- LLM 请求 dump：`/tmp/llm_debug/`（需手动开启，默认关闭）

### 端到端验证流程
1. 侧边栏选客户 → 上传转写文件 → 等分析完成
2. 打开详情 → 审核卡片（批准/拒绝）→ 搜索客户 → 点提交
3. 去简道云检查预期表/场景表是否有新记录 + customer link 是否正确

## 11. 词汇表与缩写

| 缩写/术语 | 全称/解释 |
|-----------|----------|
| JDY | 简道云 (Jiandaoyun)，帆软零代码平台 |
| CSM | Customer Success Manager，客户成功经理 |
| BI | Business Intelligence，此处指帆软 FineReport BI 系统 |
| CRM | 帆软 CRM 系统（`crm.finereporthelp.com`），存储客户联系人/任务 |
| Harness | 权力地图 Agent 的提示词+工具调度框架（`HARNESS_SYSTEM_PROMPT`） |
| MergeContext | 权力地图的运行时上下文，包含节点列表、边列表、截图 URL、会话 ID |
| 沙箱 (Sandbox) | 本地渲染 BI HTML 的无头浏览器环境 |
| SOP | Standard Operating Procedure，效率评审中建议的操作流程优化 |
| deep_req dump | `openai_compatible_agent_client.py` 中 `/tmp/llm_debug/deep_req_*.json`，调试用完整消息 dump |
| com_id | CRM 系统中的客户 UUID（36 位），不同于 JDY `_id`（24 位 hex） |
| genjin_id | JDY 标签定义的 `_id`，格式 `{"id": "698408b3..."}` |
| A1 | 钉钉应用代号，用户消息拉取管道 |
| recall | Agent 工具校验失败时的返回状态，提示 LLM 修正参数重试 |
| OPERATION_CARD_STORE | 全局 dict `{transcript_id: [cards]}`，审核状态的内存主存储 |
| PENDING_CHAT_ACTIONS | 全局 dict `{session_id: {tool_name, tool_input}}`，Chat 确认流程的暂存区 |

## 12. 部署到生产服务器

服务器：`47.98.102.197`（阿里云 ECS），通过 `https://47-98-102-197.sslip.io` 访问。

### 部署流程

```bash
# 1. 本地构建前端
cd frontend && npm run build

# 2. 上传后端文件到宿主机（deploy-feature.py），然后 docker cp 进容器
# 关键：后端源码在 Docker 镜像内，SFTP 到宿主机后必须再 docker cp
docker cp /opt/zhidang/backend/app/main.py zhidang-backend-1:/app/backend/app/main.py

# 3. 上传前端 dist/（deploy-dist.py）
# frontend/dist/ 是 bind mount (ro)，原地覆盖文件，不能 rm -rf

# 4. 重启容器
cd /opt/zhidang && docker compose restart backend frontend
```

### Docker 架构

```
docker compose up -d
├── postgres (pgdata volume)
├── backend (build: . → 源码 COPY 进镜像，非 bind mount)
│   volumes: cache_data, ./backend/static/sandbox, /opt/data:ro
└── frontend (nginx:alpine)
    volumes: ./frontend/dist (bind mount, ro), ./nginx.conf (bind mount, ro)
```

### 部署脚本一览

| 脚本 | 作用 | 缺陷 |
|------|------|------|
| `deploy-feature.py` | SFTP 上传后端/前端源文件到宿主机 | **没有 docker cp**，需手动补 |
| `deploy-dist.py` | SFTP 上传 dist/ 并重启 frontend | 可用 |
| `deploy-47-v2.py` | 全量首次部署（npm install + build） | 旧版，需更新文件列表 |
| `deploy-47.py` | 同上，旧版 | 旧版 |
| `deploy_cas.py` | CAS 认证相关部署 | 专用 |

### 宿主机 paramiko 连接

服务器密码存储在本地 `deploy-*.py` 脚本中（见 `HOST`/`USER`/`PASS` 变量）。阿里云可能限制境外 IP SSH 访问。

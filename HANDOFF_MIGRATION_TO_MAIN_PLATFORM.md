# HANDOFF — 智档迁移到客户成功主平台

最后更新：2026-06-09 by Codex  
适用场景：后续在新窗口继续做“智档功能迁移到客户成功系统主平台”的评估、方案细化和实施规划。

## 1. 这份 handoff 的目标

这份文档不是只讲“迁移建议”，而是给后续窗口一个可直接接手的当前代码主体说明。

目标是让接手人：

1. 不用重新通读整个仓库
2. 先理解智档现有代码身体长什么样
3. 再去看主平台代码，决定集成边界和配置项

用户已明确要求：

- 本轮先把“当前代码主体”讲清楚
- 配置项、接入协议、最终主平台落点，要在看完主平台代码后再判断

## 2. 当前状态快照

- 工作目录：`D:\智档`
- 当前分支：`feature/followup-records-pipeline`
- 当前提交：`61230ea`
- 当前阶段：只完成 G1 规格草案，未进入 G2 实施计划

相关文件：

- 规格草案：`docs/decisions/zhidang-main-platform-migration-spec.md`
- 本 handoff：`HANDOFF_MIGRATION_TO_MAIN_PLATFORM.md`
- 代码速览：`00_QUICKREF.md`
- 数据流：`01_DATAFLOW.md`
- 函数索引：`02_FUNCTION_INDEX.md`
- 仓库规则：`AGENTS.md`

## 3. 已确认的迁移范围

### 3.1 不迁移

明确不迁移“对话维护客户档案”。

代码落点：

- 前端：`frontend/src/pages/ChatPage.vue`
- 路由：`frontend/src/main.js`
- 后端聊天入口：`backend/app/main.py` 中 `/api/v1/chat` 链路
- 执行器：`backend/app/services/chat_executor.py`
- 工具注册：`backend/app/services/tool_registry.py:1308` `build_chat_executors`

### 3.2 需要迁移

本次迁移评估覆盖 3 个能力：

1. `生成跟进记录`
2. `生成预期&场景`
3. `权利地图维护`

### 3.3 已选中的总体策略

不要一次性把智档整体并进主平台，也不要先重写底层能力。

当前已接受的策略是：

- 主平台承接统一入口、统一登录态、统一客户上下文、统一页面壳
- 智档后端第一阶段保留为领域服务
- 先迁页面和业务流程，再判断是否拆服务或并库

详见：

- `docs/decisions/zhidang-main-platform-migration-spec.md`

## 4. 新窗口不要重读全仓，按这个顺序看

### 第一轮必读

1. 本文件 `HANDOFF_MIGRATION_TO_MAIN_PLATFORM.md`
2. `docs/decisions/zhidang-main-platform-migration-spec.md`
3. `00_QUICKREF.md`
4. `01_DATAFLOW.md`
5. `AGENTS.md`

### 第二轮按迁移目标选读

如果要先做“生成跟进记录”：

- `frontend/src/pages/ReviewPage.vue`
- `backend/app/main.py`
- `backend/app/services/followup_service.py`
- `backend/app/services/followup_review_template.py`
- `backend/app/services/jiandaoyun_writer.py`
- `backend/app/services/field_safety.py`

如果要先做“生成预期&场景”：

- `frontend/src/pages/TranscriptsPage.vue`
- `backend/app/main.py`
- `backend/app/services/analysis_pipeline.py`
- `backend/app/services/prompts.py`
- `backend/app/services/operation_executor.py`
- `backend/app/services/jiandaoyun_writer.py`

如果要看“权利地图维护”：

- `frontend/src/pages/PowerMapV2Page.vue`
- `frontend/src/pages/PowerMapPage.vue`
- `backend/app/main.py`
- `backend/app/services/power_map_service.py`

### 先不要投入时间的文件

这些文件当前不是迁移第一优先：

- `frontend/src/pages/ChatPage.vue`
- `backend/app/services/chat_executor.py`
- 视觉/UI 细枝末节文件
- 主平台接入配置猜想文档

## 5. 当前智档代码主体长什么样

### 5.1 后端骨架

后端真实入口是：

- `backend/app/main.py`

这是一个巨型单体入口，当前承担：

- 认证与 SSO
- 客户列表/客户上下文
- 转写上传、抓取、分析
- 审核卡生成与执行
- 跟进记录生成与提交
- Power Map 读取、会话、提交
- admin/runtime config
- sandbox/debug/mock/analytics

后续迁移时，不要先试图拆这个文件；先把“主平台如何调用现有能力”定清。

### 5.2 前端骨架

前端路由入口：

- `frontend/src/main.js`

当前关键路由：

- `/review` -> `frontend/src/pages/ReviewPage.vue`
- `/transcripts` -> `frontend/src/pages/TranscriptsPage.vue`
- `/power-map` -> `frontend/src/pages/PowerMapV2Page.vue`
- `/power-map-old` -> `frontend/src/pages/PowerMapPage.vue`
- `/chat` -> `frontend/src/pages/ChatPage.vue`（本次不迁）

全局壳层与客户上下文主要在：

- `frontend/src/App.vue`
- `frontend/src/stores/customer.js`

### 5.3 三条真正要迁的业务主线

#### A. 生成跟进记录

一句话：

- 从转写/上传内容或已有跟进来源出发，生成结构化跟进记录，审核后写回简道云。

#### B. 生成预期&场景

一句话：

- 从转写或图片输入中抽取事实，和客户现有预期/场景做比对，生成操作卡，审核后写回简道云。

#### C. 权利地图维护

一句话：

- 读取外部 Power Map / BI 图谱，在会话态中进行 AI 修改、预览、commit/discard，并同步正式图谱。

## 6. 逐页代码地图：页面 -> API -> 服务 -> 外部依赖

### 6.1 生成跟进记录

前端主页面：

- `frontend/src/pages/ReviewPage.vue`

相关前端特征：

- 页面本身既承担“生成”，也承担“审核/提交”
- 依赖客户上下文、联系人、任务、标签树、模板配置
- 用户真正操作的是结构化表单，不是单纯文本框

后端入口在：

- `backend/app/main.py:4261` `generate_review`
- `backend/app/main.py:4377` `submit_review`
- `backend/app/main.py:4637` `followup_generate`
- `backend/app/main.py:4641` `followup_submit`
- `backend/app/main.py:2444` `customer_contacts`
- `backend/app/main.py:2468` `customer_tasks`

核心服务：

- `backend/app/services/followup_service.py:167` `FollowupService`
- `backend/app/services/followup_review_template.py`
- `backend/app/services/jiandaoyun_writer.py:13` `JiandaoyunWriter`
- `backend/app/services/field_safety.py`
- `backend/app/services/jiandaoyun_client.py:30` `JiandaoyunClient`

后端真实职责拆分：

- `main.py`：路由、鉴权、客户上下文拼装、trace
- `FollowupService`：LLM 输入拼装、记录结构生成、提交 payload 组织
- `followup_review_template.py`：模板读写、system prompt 组装、记录渲染
- `JiandaoyunWriter`：写回简道云
- `field_safety.py`：字段级写入约束

外部依赖：

- 简道云
- CRM 联系人/任务接口
- LLM 配置

迁移时最关键的不是页面搬运，而是这几个输入是否在主平台能稳定提供：

- 当前客户标识
- 联系人列表
- 任务列表
- 跟进标签树
- 跟进模板配置能力

### 6.2 生成预期&场景

前端主页面：

- `frontend/src/pages/TranscriptsPage.vue`

相关前端特征：

- 同时承载“转写/图片输入入口”和“操作卡审核编辑”
- 有分页、选择、多卡片编辑、审批态切换
- 前端会对场景与预期关系做一定映射和联动

后端主链路在：

- `backend/app/main.py:1824` `transcript_upload`
- `backend/app/main.py:2085` `start_transcript_analysis`
- `backend/app/main.py:2874` `operations_review`
- `backend/app/main.py:2908` `execute_operations`

分析/抽取/比对核心：

- `backend/app/services/analysis_pipeline.py:31` `run_analysis_pipeline`
- `backend/app/main.py` 中 `run_extraction_task`
- `backend/app/main.py` 中 `comparison_task`
- `backend/app/services/prompts.py`
- `backend/app/services/operation_executor.py`
- `backend/app/services/jiandaoyun_writer.py:13` `JiandaoyunWriter`

运行态关键内存对象：

- `TASK_PROGRESS`
- `OPERATION_CARD_STORE`

这条链路的真实复杂点：

- 不是“上传文件”本身
- 而是提取 -> 比对 -> 生成操作卡 -> 审核 -> 执行写回的完整闭环

接手人需要优先知道：

- 审核卡并不是数据库长期态，存在内存缓存语义
- 写回不能绕开 `operation_executor` / `JiandaoyunWriter`
- 字段映射不是只改一个文件，而是配置、别名、prompt 联动

强相关文件：

- `backend/app/config/jiandaoyun_field_mapping.json`
- `backend/app/services/tool_registry.py`
- `backend/app/services/prompts.py`

### 6.3 权利地图维护

前端页面：

- 主用页：`frontend/src/pages/PowerMapV2Page.vue`
- 旧页：`frontend/src/pages/PowerMapPage.vue`

后端主链路在：

- `backend/app/main.py:3296` `power_map_get`
- `backend/app/main.py:3421` `power_map_chat_v2`
- `backend/app/main.py:3500` `power_map_commit`
- `backend/app/main.py:3513` `power_map_discard`

核心服务：

- `backend/app/services/power_map_service.py:8959` `get_power_map`
- `backend/app/services/power_map_service.py:9846` `chat_power_map_v2`
- `backend/app/services/power_map_service.py:10045` `commit_power_map_session`
- `backend/app/services/power_map_service.py:10079` `discard_power_map_session`

这条线和另外两条最大的不同：

- 它不是常规表单 CRUD
- 它依赖 iframe / sandbox / 外部 BI 页面
- 它有会话态图结构
- 它有 commit/discard 语义
- 它有版本切换和正式/沙箱读取差异

真实复杂点在这些能力：

- 图谱读取与版本决议
- AI 改图的流式返回
- 会话中图结构暂存
- sandbox 预览
- 最终提交到正式图谱

因此迁移权利地图时，优先迁的是：

- 页面入口
- 客户上下文
- token/鉴权透传
- iframe/代理/HTTPS/SSE 兼容

不是先重写 `power_map_service.py`。

## 7. 当前代码里的公共耦合点

这些是三个待迁模块共享、而且容易在主平台接入时踩雷的地方。

### 7.1 客户上下文

强相关后端入口：

- `backend/app/main.py:2121` `customers_list`
- `backend/app/main.py:2444` `customer_contacts`
- `backend/app/main.py:2468` `customer_tasks`

强相关前端状态：

- `frontend/src/App.vue`
- `frontend/src/stores/customer.js`

迁移判断前提：

- 主平台必须先搞清楚自己如何传 `company_id / com_id / company_name`
- 没有这层，三条能力都会出现隐性故障

### 7.2 鉴权与运行时配置

相关落点：

- `backend/app/main.py` 中 auth / sso / admin config / llm config
- `backend/app/main.py` 中 `get_jiandaoyun_runtime_config`
- `backend/app/main.py` 中配置加密逻辑

这一层现在先不要定迁移方案。  
等接手窗口把主平台代码读完，再决定：

- 是主平台统一鉴权后透传 token
- 还是保留智档已有 JWT/SSO 边界
- 还是做网关代理

### 7.3 写回安全

所有简道云写入都应经过：

- `backend/app/services/operation_executor.py`
- `backend/app/services/jiandaoyun_writer.py`
- `backend/app/services/field_safety.py`

不要在迁移中为了“方便接主平台”而绕开这层。

### 7.4 内存态 / 会话态

当前不是所有运行态都落库：

- 操作卡：`OPERATION_CARD_STORE`
- 任务进度：`TASK_PROGRESS`
- Power Map 会话：`power_map_service.py` 中 session store

这意味着：

- 主平台迁页面，不等于立刻能托管所有运行时
- 迁移第一阶段更适合“调用现有智档后端”

## 8. 推荐迁移顺序，以及为什么这样排

### 第一阶段：生成跟进记录

原因：

- 页面边界清晰
- 对外部系统依赖相对集中
- 比 transcripts 和 power-map 更容易先形成主平台可见价值

### 第二阶段：生成预期&场景

原因：

- 这是智档核心主链路
- 但审核卡、写回安全、字段映射联动更复杂

### 第三阶段：权利地图维护

原因：

- 外部依赖最多
- 运行态最特殊
- 对主平台前端壳层、代理、iframe、SSE、HTTPS 兼容要求最高

## 9. 新窗口的最小接手动作

后续新窗口第一轮只建议做下面这些事：

1. 先读完本 handoff 指向的智档代码主体
2. 再去读主平台代码
3. 产出“主平台代码事实”而不是先猜配置项
4. 基于两边真实代码，再写功能映射表和 G2 计划

第一轮不建议直接开始：

- 改智档主代码
- 设计最终配置项
- 迁权利地图
- 合并数据库
- 重写后端单体结构

## 10. 后续输出物建议

当接手窗口完成“主平台代码阅读”后，再产出这些东西：

1. 主平台现状摘要
2. 智档能力 -> 主平台模块映射表
3. 第一阶段“生成跟进记录”G2 计划
4. 主平台与智档之间的上下文/鉴权/调用边界

在此之前，不要把“主平台最终配置项”写死。

## 11. 当前门禁状态

- G1 规格草案：已完成
- G1 人工批准：待确认
- G2 实施计划：未开始
- 代码迁移：未开始

对应规格文件：

- `docs/decisions/zhidang-main-platform-migration-spec.md`

## 12. 一句话交接结论

这次 handoff 的重点不是告诉新窗口“怎么接主平台配置”，而是先把智档现有代码主体、三条待迁业务主线、真实页面/API/服务边界讲清楚。接手人应该先基于这份代码地图读智档，再去读主平台，然后再决定集成方案。

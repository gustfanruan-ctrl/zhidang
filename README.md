# 智档

智档是一个面向客户成功团队的 AI 辅助运营系统。它把会议转写、截图、聊天指令和客户档案维护串起来，帮助团队把“客户说了什么”转成“结构化记录、待审核操作、后续跟进和权利地图调整”。

当前项目的核心目标不是做通用聊天，而是把几类高频客户成功工作流程产品化：

- 转写/图片输入 -> 提炼客户预期与业务场景
- 新事实 vs 简道云已有档案 -> 生成可审核的新增/修改/删除操作
- 自然语言维护客户档案
- 自然语言维护客户权利地图（Power Map）
- 生成跟进记录、审核卡片等交付物

## 核心功能

### 1. 转写与图片结构化
- 上传会议转写、图片或从钉钉拉取内容
- 用 LLM 提炼客户预期、业务场景和相关事实
- 将结果标准化为系统内部的 facts / operation cards 结构

对应实现：
- 后端入口：`backend/app/main.py`
  - `/api/v1/transcript/upload`
  - `/api/v1/transcripts/{transcript_id}/analyze`
  - `/api/v1/agent/extraction/task`
  - `/api/v1/agent/comparison/task`
- 提示词与抽取规则：`backend/app/services/prompts.py`
- Agent 工具与字段映射：`backend/app/services/tool_registry.py`

### 2. 客户档案比对与审核写回
- 将本次提取出的预期/场景与简道云已有数据做比对
- 生成 create / update / delete / skip 操作卡
- 前端审核后，再统一写回简道云

对应实现：
- 操作卡审核与执行：`backend/app/main.py`
  - `/api/v1/operations/review`
  - `/api/v1/operations/execute`
- 执行器：`backend/app/services/operation_executor.py`
- 字段安全策略：`backend/app/services/field_safety.py`
- 简道云客户端/写入：  
  `backend/app/services/jiandaoyun_client.py`  
  `backend/app/services/jiandaoyun_writer.py`

### 3. Chat 档案维护
- 在聊天页用自然语言查询、新增、修改、删除“预期表 / 场景表”
- 写入前先生成待确认预览
- 确认后才真正落库到简道云

对应实现：
- API：`backend/app/main.py` -> `/api/v1/chat`
- Tool Call 编排：`backend/app/services/agent_runner.py`
- 写入预览和参数归一化：`backend/app/services/chat_executor.py`
- 前端页面：`frontend/src/pages/ChatPage.vue`

### 4. Power Map 权利地图维护
- 读取客户权利地图及版本信息
- 支持自然语言增删节点、调整汇报关系、加备注、自动布局
- 先在会话内存中修改，再由用户确认 commit 到 BI

对应实现：
- API：`backend/app/main.py`
  - `/api/v1/power-map/{company_id}`
  - `/api/v1/power-map/{company_id}/chat`
  - `/api/v1/power-map/{company_id}/chat_v2`
  - `/api/v1/power-map/{company_id}/commit`
  - `/api/v1/power-map/{company_id}/discard`
- 核心服务：`backend/app/services/power_map_service.py`
- 前端页面：`frontend/src/pages/PowerMapPage.vue`

### 5. 跟进记录与审核卡片
- 基于会议内容生成跟进记录
- 生成审核卡片并支持提交
- 作为客户成功同学的交付辅助层

对应实现：
- 相关接口：`backend/app/main.py`
  - `/api/v1/review/generate`
  - `/api/v1/review/submit`
  - `/api/v1/followup/generate`
  - `/api/v1/followup/submit`
- 跟进服务：`backend/app/services/followup_service.py`

## 系统怎么实现

### 1. 后端
- 技术栈：FastAPI + SQLAlchemy + Alembic
- 真实应用入口：`backend/app/main.py`
- 特点：API 路由、鉴权、Agent 编排、Power Map 代理都集中在这个文件，业务体量较大

后端主要承担四件事：
- 统一提供 API 和鉴权
- 管理 LLM 调用、提示词、工具调用和 fallback
- 与简道云、CAS/BI、Power Map 外部系统通信
- 保管短周期会话态，如 operation cards、Power Map 会话上下文

### 2. 前端
- 技术栈：Vue 3 + Vite + Pinia
- 主要页面位于 `frontend/src/pages/`

当前高频页面包括：
- `TranscriptsPage.vue`：转写上传与分析
- `ReviewPage.vue`：操作卡审核
- `ChatPage.vue`：客户档案聊天维护
- `PowerMapPage.vue`：权利地图维护

### 3. Agent / Tool 调用机制
- 系统不是只让模型直接输出文本，而是让模型通过工具操作结构化数据
- Tool schema、字段别名、写入约束集中在 `tool_registry.py`
- 真正执行写入前，会经过预览、字段校验和安全策略

这套设计的目的，是把“LLM 会说”变成“LLM 能以可审核、可回滚、可追踪的方式做事”。

### 4. 外部系统集成
- 简道云：客户主档、预期表、场景表、跟进记录等最终落地位置
- CAS / BI：Power Map 和相关企业数据读取
- 钉钉：会议内容拉取

## 目录结构

```text
backend/                 FastAPI 后端
  app/
    main.py              主 API 入口
    services/            Agent、Power Map、跟进、简道云等核心服务
    config/              字段映射等配置
  tests/                 后端测试
frontend/                Vue 3 前端
alembic/                 Alembic 迁移脚本
docs/                    补充文档
scripts/                 运维/辅助脚本
```

## 本地运行

### Docker
```bash
docker compose up --build
```

### 后端
```bash
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端
```bash
cd frontend
npm install
npm run dev
```

### 数据库迁移
```bash
alembic upgrade head
```

## 关键配置

从 `.env.example` 复制环境变量后，通常至少需要配置：

- `DATABASE_URL`
- `JWT_SECRET`
- LLM 相关配置
- 简道云 API 配置
- Power Map / BI 登录或票据相关配置

如果只是本地快速开发，可以先使用 SQLite：

```bash
DATABASE_URL=sqlite:///./zhidang.db
```

## 关键设计取舍

- 写入类操作默认走“先预览、后确认”
- 字段映射与字段安全放在后端统一控制，不把写入细节散落到 prompt 里
- Power Map v2 使用内存会话保存本轮图状态，commit / discard 后清理
- 外部系统较多，所以很多问题本质上是“系统编排问题”，不只是前端或提示词问题

## 快速定位建议

- 档案聊天问题：先看 `backend/app/main.py`、`agent_runner.py`、`chat_executor.py`
- 抽取/审核问题：先看 `prompts.py`、`tool_registry.py`、`operation_executor.py`
- Power Map 问题：先看 `power_map_service.py` 和 `main.py` 中的 `/power-map` 路由
- 简道云字段不对：先看 `backend/app/config/jiandaoyun_field_mapping.json`

## 健康检查

- `/health`
- `/api/v1/health`
- `/api/v1/system/status`

## 说明

- 根目录还有一个 `main.py`，它不是当前生产主应用入口；真实后端入口是 `backend/app/main.py`
- 当前仓库里已经沉淀了若干维护文档，如 `00_QUICKREF.md`、`01_DATAFLOW.md`、`02_FUNCTION_INDEX.md`，适合继续深入排查时配合阅读

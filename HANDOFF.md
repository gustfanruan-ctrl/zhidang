# HANDOFF — 接替说明

最后更新：2026-05-25 by Claude Code session
下一实例请先读此文件，再读 PROJECT.md，最后看 CLAUDE.md。

## 1. 当前任务一句话

跟进记录 pipeline + 审核卡片执行流的多项缺陷修复（com_id 格式、标签 ID 映射、确认按钮、沙箱持久化），**代码已写完并部署到容器，等待用户验证**。

## 2. 上下文锚点

### 当前分支与提交
- 分支：`feature/followup-records-pipeline`
- 最近已提交：
  - `62196ae` docs: add PROJECT.md
  - `6a65070` fix: followup补传com_id(CRM UUID) + genjin标签ID映射 + review_id
  - `4bfdc4c` fix: 审批状态从DB恢复 + company_id选择后落盘 + 去掉pending误显
  - `32de6b6` fix: company_id 不再硬编码 "demo" + 审核卡片从DB恢复审批状态 + 公司选择器默认值兜底
  - `193b3ec` feat: 审核卡片公司选择器兜底 + 异步效率评审

### 未提交的改动（全部来自本轮会话，需要提交）

| 文件 | 改动内容 |
|------|---------|
| `backend/app/schemas/operation.py` | `OperationExecuteRequest` 新增 `card_overrides` 字段 |
| `backend/app/services/prompts.py` | Chat system prompt 新增规则 1.5（强制 LLM 调 write 工具） |
| `docker-compose.yml` | backend 新增 `./backend/static/sandbox` bind mount |
| `frontend/src/pages/ChatPage.vue` | 打字"确认/好的/etc"自动走 confirm 流程 |
| `frontend/src/pages/PowerMapV2Page.vue` | iframe key 绑定 `commitRefreshKey`，提交后自动刷新 |
| `frontend/src/pages/TranscriptsPage.vue` | 审核卡片多个改动（见下方详情） |
| `frontend/src/stores/powerMapChat.js` | state 新增 `commitRefreshKey`，commit 成功后自增 |

### TranscriptsPage.vue 改动汇总（重要，改动量大）

| 行号范围 | 内容 |
|---------|------|
| 320-330 | 每张卡片新增审批状态 badge（已批准/已拒绝/待审核） |
| 432-480 | 提交按钮上方新增搜索式公司选择器（替代简单 dropdown） |
| 796-804 | `cardGroups` 的 `approved`/`rejected` 逻辑：去掉 auto-approve fallback |
| 806 | card item 新增 `customerId` 字段 |
| 825-838 | 新增 `cardCustomerId`/`targetCompanyId`/`effectiveCompanyId` 等 computed |
| 882-897 | `loadCardsFromTranscript` 新增 `reviewState` hydration + `targetCompanyId` 默认值 |
| 982-1001 | `submitCards` 发送 `card_overrides` + `field_updates` |
| 941-980 | `switchCardType` 新增 change_items 互转映射（场景↔预期） |
| 838-855 | `searchReviewCustomers` 远程搜索客户（突破 500 条限制） |

## 3. 已验证的事实

1. **容器内代码 ≠ 宿主机代码**：后端源码 `build: .` 进镜像，无 bind mount。SFTP 到 `/opt/zhidang/` 后必须 `docker cp` 进容器。已验证：grep 容器内 main.py 缺少 debug 行。

2. **com_id 格式是 CRM UUID（36 位），不是 JDY _id（24 位 hex）**：真实 JDY 跟进记录中 `comid` 值为 `c191f13c-3e24-4921-974e-b33022d8adbe` 格式。我们的代码原先用 `company_id`（JDY `_id`）兜底，已修复。

3. **跟进标签 genjin_id 非随机**：每个 `(level1, level2)` 组合对应固定 JDY 标签定义 ID。已从 JDY 拉取 14 组映射更新到 `review_tag_tree.json`。

4. **预期表/场景表 JDY 记录 `com_id` 和 `relation` 字段全空**：`operation_card_logs` 中所有 create 成功的记录，JDY 响应里这两个字段都是空/null。

5. **Chat 确认按钮灰色根因是后端 `needs_confirmation=false`**：LLM 生成确认话术但不调 write 工具 → `pending_write=None` → 前端按钮一直灰色。不是前端渲染 bug。

6. **沙箱 HTML 需要手动下载 + 持久化**：镜像不含沙箱资源，已加 bind mount `./backend/static/sandbox`，需首次触发 `download_bi_resources`。

## 4. 已排除的假设

1. ~~"前端确认按钮灰色是 CSS/条件渲染问题"~~ → 实际是 `needsConfirm` ref 值为 false，因为后端没返回 `needs_confirmation: true`。证据：devtools 看 network response。

2. ~~"company_id 传的是对的，JDY 自己没关联"~~ → 实际传的是 JDY `_id`，而 JDY 跟进表 `comid` 字段期望 CRM UUID。证据：对比人工填写数据。

3. ~~"docker compose restart 后容器跑的就是最新代码"~~ → 后端镜像无 bind mount，restart 不生效。证据：容器内 grep 和宿主机 grep 结果不一致。

4. ~~"手动新增的卡片提交后字段为空是 LLM 没提取"~~ → 实际是 `change_items: []` 时 `if change_items:` 守卫跳过 field_updates 追加。证据：日志显示 JDY create 成功但 `detail_brief` 为空。

5. ~~"场景切预期的卡片应该自动用新表的 entry_id"~~ → 切换只改了 `target_form` 没改 `lookup_widget`，导致用场景表的 widget 写预期表。已修复：覆盖 target_form 时同步切 lookup_widget。

## 5. 当前怀疑/未验证假设

1. **（高概率）审核卡片公司选择器选择后执行，customer_id 仍未写入 JDY**：虽然 deploy 日志显示 `company_id='67f8ed839f...'` 已接收、DB 已落盘，但用户之前反馈"还是不行"。可能是容器旧代码导致——本次会话最后一次性 `docker cp` 了所有 services/*.py，用户尚未重新验证。

2. **（中概率）预期表/场景表的 `com_id` 字段需要额外处理**：跟进记录需要 CRM UUID 的 `comid`，但预期/场景的表可能有不同要求。对比人工填写数据时预期表也没有 com_id——可能这两种表不需要 com_id，只需要 lookup 字段正确即可。

3. **（低概率）`genjin_id` 映射表不完整**：当前只有 14 组映射，真实 JDY 可能有更多标签组合。如果用户选了不在映射表中的标签，`tag_id` 为空，JDY 可能接受空值。

## 6. 下一步动作

### 第 1 步：验证容器最新代码效果
让用户做一次完整操作：上传 → 分析 → 审核 → 搜客户 → 选客户 → 提交。然后检查：
```sql
-- 检查最新 JDY 记录
SELECT jiandaoyun_response->'data'->>'relation' AS relation,
       jiandaoyun_response->'data'->>'com_id' AS com_id
FROM operation_card_logs ORDER BY executed_at DESC LIMIT 3;
```

### 第 2 步：提交未提交的改动
```bash
git add backend/app/schemas/operation.py backend/app/services/prompts.py \
        docker-compose.yml frontend/src/pages/ChatPage.vue \
        frontend/src/pages/PowerMapV2Page.vue frontend/src/pages/TranscriptsPage.vue \
        frontend/src/stores/powerMapChat.js PROJECT.md
git commit -m "fix: 多项修复 - 确认按钮/iframe刷新/card_overrides/沙箱持久化/chat prompt"
```

### 第 3 步：验证跟进记录新字段
用户提交一条跟进记录后：
```sql
SELECT raw_record->>'review_id' AS review_id,
       raw_record->>'comid' AS comid,
       raw_record->'genjin' AS genjin
FROM followup_records ORDER BY created_at DESC LIMIT 1;
```
预期：`review_id` 为 36 位 UUID，`comid` 为 CRM UUID 格式，`genjin` 包含 `genjin_uuid`。

### 第 4 步：清理垃圾文件
```bash
rm -f dry_run_review.py nul
git branch -D worktree-agent-a0ec4e4a18340f18a 2>/dev/null
```

### 第 5 步：如果容器代码又变旧了
在宿主机上执行：
```bash
# 一次性同步所有 backend 文件到容器
for f in $(find /opt/zhidang/backend/app -name '*.py'); do
    rel=${f#/opt/zhidang/}
    docker cp "$f" "zhidang-backend-1:/app/$rel"
done
docker compose restart backend
```

## 7. 不要碰的地方

- **`_run_llm_tool_loop` 的收敛逻辑**（3 个 exit point）— 看似可以合并且代码重复，但这 3 个出口各有不同语义，且 `_maybe_queue_review` 闭包依赖它们设置的 `exit_reason`
- **`analysis_pipeline.py:105` 的 `company_id or ""`** — 不要改回 `or "demo"`，空字符串是让 `exec_fetch_profile` 走 `match_customer` 回退
- **`deploy-feature.py` 的 npm build 步骤** — 虽然在服务器上失败（无 package.json），但这是已知的，不要删掉——有时服务器有 node 环境
- **`frontend/dist/` 目录** — 不要 `rm -rf`，这是 bind mount
- **`PENDING_CHAT_ACTIONS` 内存 dict** — 看起来是"没持久化的隐患"，但当前对话周期短，暂不需要改。如果非要改，用 DB 而非 Redis（不引入新依赖）
- **`power_map_service.py` 的 `_TOOL_RESULT_COMPRESS_KEEP_FIELDS`** — 看着像 magic list，但每个字段都有业务原因，删一个可能让 LLM 上下文膨胀或丢失关键信息

## 8. 用户偏好与项目约定

- **用户是 CSM 业务方 + 技术决策者**，能 SSH 到服务器、查 SQL、读 JDY 数据
- **偏好轻量改动**，反感大重构和过度抽象。"三个相似行比提前抽象好"
- **反馈直接**，会说"你修了个寂寞"——说明改动没生效或没对准根因。优先排查"代码是否真正在执行"（容器旧代码的问题出现过多次）
- **先调研后写代码**，会要求"别改代码，先给结论"
- **部署流程**：本地写→build 前端→SFTP→docker cp→restart。你没法直接 SSH（阿里云限 IP），但可以通过 paramiko + SFTP 上传文件
- **提交信息格式**：`类型: 中文描述`，如 `fix: followup补传com_id (CRM UUID) + genjin标签ID映射`
- **服务器**：`47.98.102.197`，`https://47-98-102-197.sslip.io`。容器名：`zhidang-backend-1`、`zhidang-frontend-1`、`zhidang-postgres-1`
- **数据库**：`docker exec zhidang-postgres-1 psql -U zhidang -d zhidang`

## 9. 待用户确认的悬而未决问题

1. **公司选择器选择后提交，customer_id 是否真的写入了 JDY？** 本轮最后一次性同步了所有 container 代码，需用户重新验证。
2. **预期表/场景表的 `com_id` 是否需要显式写入？** 跟进记录需要，但预期/场景表可能只需要 lookup 字段。
3. **效率评审采样率是否调整？** 当前默认 20% 随机采样，≤8 轮不审。用户说"每周末人工审核后再决定"。
4. **跟进标签映射表是否需要从 JDY 动态拉取？** 目前是静态映射文件，新增标签需手动更新。
5. **`feature/followup-records-pipeline` 何时合并到 master？** 等所有修复验证通过后可合并。
6. **空闲的 `worktree-agent-*` 分支是否删除？**

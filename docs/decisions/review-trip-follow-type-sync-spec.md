---
topic: review-trip-follow-type-sync
created_at: 2026-06-05T13:55:00+08:00
created_by: agent
risk_level_proposed: L1
---

# 目标
在 `/review` 页面审核编辑阶段，当用户在“关联出差”区域勾选任意出差记录时，前端自动将“跟进类型”切换为 `线下跟进`。

# 范围
- 仅修改 [frontend/src/pages/ReviewPage.vue](/D:/智档/frontend/src/pages/ReviewPage.vue) 的前端联动逻辑。
- 仅在审核编辑表单内，根据 `selectedTaskIds` 的勾选状态更新 `reviewData.follow_type`。
- 保持现有“跟进类型”下拉可见且可手动调整，不修改后端提交 payload 结构。

# 非目标
- 不修改后端 `/api/v1/followup/submit` 写入逻辑。
- 不修改 AI 生成 `follow_type` 的提示词或默认值。
- 不在本次需求里定义“取消所有出差勾选后是否自动切回线上跟进/内部沟通”。

# 风险假设
- 现有业务规则接受“勾选任意出差 = 当前记录应归类为线下跟进”这一单向联动；如果业务其实需要双向或可撤销联动，则本次实现需要调整。
- `selectedTaskIds` 只代表出差关联，不会被复用于别的非出差语义对象；因此基于它触发 `线下跟进` 不会误伤其他字段。

# 备选方案
## 方案 A：只在提交时偷偷覆盖 payload 中的 `follow_type`
- 优点：
- 表单展示不变，实现位置集中在提交入口。
- 缺点：
- 用户在提交前看到的跟进类型仍可能与最终写入值不一致，违背审核页“所见即所得”。
- 结论：Reject
- 原因：需求明确是前端变更，用户在 `/review` 页面就应看到类型已经变成 `线下跟进`。

## 方案 B：勾选出差后在前端实时改写 `reviewData.follow_type`
- 优点：
- 行为直观，和审核编辑页的即时反馈一致。
- 改动范围小，只涉及本地表单状态联动。
- 缺点：
- 若未来要支持“取消勾选后自动回退到原值”，还需要补充记忆原始值或新增规则。
- 结论：Accept
- 原因：满足当前需求，且风险最低。

# 最终选型
采用方案 B：在 `ReviewPage.vue` 中监听“关联出差”勾选集合，当 `selectedTaskIds` 非空且存在 `reviewData` 时，将 `reviewData.follow_type` 自动设为 `线下跟进`。

预期实现边界：
- 只做单向联动：从“勾选出差”推导“线下跟进”。
- 不在本次实现里自动回退原类型。
- 不新增接口、不改 schema、不改数据库或简道云字段配置。

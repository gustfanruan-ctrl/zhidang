---
topic: review-trip-follow-type-sync
spec_ref: docs/decisions/review-trip-follow-type-sync-spec.approved.md
risk_level: L1
status: draft
parallelizable: false
---

# Tasks

## Task T1: Add trip-to-follow-type form linkage
- Files:
  - frontend/src/pages/ReviewPage.vue
- Exports Added:
  - None
- Exports Modified:
  - None
- Dependencies Added:
  - None
- RED Test:
  - name: Review manual check - selecting any trip flips follow type to `线下跟进`
  - expected_failure_reason: current page keeps `selectedTaskIds` and `reviewData.follow_type` independent, so selecting a trip does not change the follow type field
- Acceptance Checklist:
  - [ ] When `reviewData` exists and the user selects any trip, `reviewData.follow_type` becomes `线下跟进`
  - [ ] Existing manual selection of `跟进类型` still works before any trip is selected
  - [ ] Submit payload shape remains unchanged
  - [ ] No backend file is modified for this task

## Task T2: Verify no regression in nearby review state handling
- Files:
  - frontend/src/pages/ReviewPage.vue
- Exports Added:
  - None
- Exports Modified:
  - None
- Dependencies Added:
  - None
- RED Test:
  - name: Review manual check - customer switch still clears task selections without crashing
  - expected_failure_reason: the new linkage touches the same local state cluster as `selectedTaskIds`, so we need to confirm the existing customer-switch reset path still behaves correctly
- Acceptance Checklist:
  - [ ] Switching customer still clears `selectedTaskIds`
  - [ ] Existing `reviewData.yuqi_id` reset logic remains intact
  - [ ] New watcher/logic does not run when `reviewData` is null

# Impact Analysis
- Impact is limited to the `/review` frontend editing experience.
- No API contract, write payload schema, backend route, or database behavior changes.
- The main behavioral tradeoff is intentional: this is a one-way assistive autofill and does not auto-revert when trips are unchecked.

# Parallelization Plan
- `parallelizable: false`
- This is a single-file UI state change with adjacent state-reset logic in the same component; splitting it would add overhead without reducing risk.

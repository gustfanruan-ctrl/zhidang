# Change Context Note

Task: T4
Files Touched:
- frontend/src/pages/ReviewPage.vue
- docs/decisions/review-trip-follow-type-sync-spec.md

## Reason from blame/log/PR
- `git log --follow --oneline -- frontend/src/pages/ReviewPage.vue` shows this page accumulated the review flow in stages: initial review page (`490b26f`), followup submission fixes, then customer contact and trip binding (`5198af1`), follow-type standardization to `线上跟进 / 线下跟进 / 内部沟通` (`7531460`), and later the trip area moved below contacts (`2188eb3`).
- `git blame` around the review form shows the current `follow_type` selector and `selectedTaskIds` task checkbox list were introduced by different commits, so there is no existing automatic linkage between them yet; the current behavior is user-edited `follow_type` plus independently selected trips.
- The user request is narrowly scoped to the `/review` frontend behavior: when any trip is selected in the “关联出差” area, auto-switch `跟进类型` to `线下跟进`.

## What fence may exist here
- The existing fence is the standardized follow-type enum added earlier: `线上跟进 / 线下跟进 / 内部沟通`. Auto-filling must stay inside this enum and must not invent a new status or touch backend mapping.
- The trip selector is optional and multi-select. The safest interpretation is additive UI assistance: selecting at least one trip sets `follow_type` to `线下跟进`, but this task should not rewrite other review fields or alter submit payload shape.

## What I will not change yet
- I will not change backend `/api/v1/followup/submit` handling or schema mapping in this task, because the requested behavior is a frontend form linkage before submission.
- I will not add reverse auto-switching when trips are unselected unless the product rule is explicitly confirmed later; this task only covers “勾选了出差时自动改为线下跟进”.
- I will not change AI generation defaults for `follow_type`; the auto-switch belongs to the manual review/edit stage only.

## Evidence
- `git log --follow --oneline -- frontend/src/pages/ReviewPage.vue`
- `git blame -L 188,320 -- frontend/src/pages/ReviewPage.vue`
- User requirement in chat: “如果关联出差中勾选了出差，则跟进类型自动改为线下跟进”

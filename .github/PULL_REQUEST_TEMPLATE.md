<!-- FDE-Workflow PR template. Do not delete sections; mark N/A where appropriate. -->

## Summary
<one paragraph: what this PR does, in business terms>

## Risk level
- [ ] L1 (low — text, comment, private refactor, test additions)
- [ ] L2 (medium — module-internal behavior change)
- [ ] L3 (high — public API / concurrency / persistence / auth / dependency / >30-day code removal)

## Gates
- [ ] **G1 — Design** signed: `docs/decisions/<topic>-spec.approved.md`
- [ ] **G2 — Plan** signed: `docs/decisions/<topic>-plan.approved.md`
- [ ] **G3 — Release** signed (if L3 or trigger fired): `docs/decisions/<topic>-g3.approved.md` — _N/A if not triggered_
- [ ] **G4 — Merge** trailer added to the merge commit by a human: `Approved-G4-Merge: <name> <YYYY-MM-DD>`

## Evidence manifest
Path: `.fde/evidence/<branch>/manifest.yaml`

- [ ] Manifest exists
- [ ] All tasks have `pass` status
- [ ] Mutation score meets threshold

## Change Context Notes
For each task touching existing code:
- [ ] `.fde/evidence/<branch>/T<n>/change-context-note.md` present
- [ ] Reason from blame/log/PR is concrete (real commit hashes)
- [ ] Fence section is not a stub

## Memory updates
- [ ] None
- [ ] Listed in manifest under `memory_updates:` with reason

## Rollback plan (L3 only)
<command sequence or PR operations to roll back within 10 minutes>

---

<!--
Reminder to human reviewers:
- Do NOT auto-merge.
- Add the Approved-G4-Merge trailer to the merge commit yourself.
- If anything in the FDE Gates CI check is red, do not override unless this is an incident bypass (see engineering-gates.md §7.1).
-->

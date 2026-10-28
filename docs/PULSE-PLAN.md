# AASS Pulse execution plan

Scope: one All Tests view, bounded isolated evaluations, metadata-first diagnostic
export, and general execution reliability repairs. No extra runtime agents/models,
new dependencies, production self-repair, or release-gate exceptions.

Baseline: uploaded expense run fa0497d9843d408fafdfa3cdfbefa114 wrote all three
files by step 3, then rewrote files and rejected three schemas without tests or
review. Uploaded files independently ran 12 tests: 3 passed, 6 failed, 3 errors.
Malformed JSON can be overwritten. Reserved budget 63,775 is not billable usage.
The earlier two-file draft is uncommitted work from this session, not user code.

## Milestones and acceptance

- [x] A: pulse/events.py, supervisor/worker hooks. Incremental versioned bounded
  events, fixed error categories, causal IDs and reported usage. No raw responses.
- [x] B: worker_agent.py, crdal_supervisor.py. Action-specific required fields;
  retained failure feedback; verification on runnable changed test snapshots;
  multi-file ineffective-loop evidence; unchanged hard limits and judge gate.
  Focused: python -m pytest tests/test_protocols.py tests/test_supervisor.py.
- [x] C: pulse/manifest.json, benchmarks.py, engine.py. Eight stable benchmarks,
  independent Docker acceptance tests, isolated per-run workspaces, bounded
  subprocess deadlines/cancellation/locks, default no model calls, explicit live
  local/cloud options. Fixed manifest hash qualifies comparisons.
- [x] D: pulse/view.py, setup_wizard.py/controller.py. One All Tests entry,
  queued responsive updates, real completion counts, elapsed time, cancellation,
  native sound fallback, review/export actions. Test under Tk + Windows CI.
- [x] E: pulse/report.py. Review manifest, optional sections, metadata-only safe
  defaults, no arbitrary files, no automatic upload. Seeded secret/path/model
  text injection tests; validate ZIP names, sizes and reopening.
- [ ] F: full tests with actual Docker/Postgres, lint/security; package installed
  Pulse smoke/evaluation on native Windows, preserving existing all release gates.
- [ ] G: commit/push; monitor automatically triggered complete verification;
  publish only gated exact ZIP; independently verify assets. Physical Win10/live
  model acceptance remains explicitly unverified in this cloud environment.

Default suite distinguishes harness/fixture evidence from live AI capability.
Live budgets remain shared and bounded; missing prerequisites become blocked,
never passed. Optional hardware telemetry is unavailable unless supported.

Progress: A–E implemented. Focused protocol/supervisor/UI-headless tests passed;
real Docker benchmark suite and original uploaded failing baseline reproduced.
First complete suite: 491 passed, 4 skipped, one package fixture failure. The
failure exposed static Pulse assets outside the package inventory override;
corrected inventory placement. Subsequent complete suite: 495 passed, 4 skipped.
Final loop checks distinguish productive AST changes from cosmetic rewrites and
repeated failures on an unchanged semantic snapshot; focused regressions passed.
Complete candidate suite: 497 passed, four Windows-only skips. Final focused
real-tool checks: 59 passed; final report unit checks: 11 passed. Lint, format,
medium/high source scan and diff checks passed. Native Windows
UI, installed Pulse and all original gates remain mandatory before publication.

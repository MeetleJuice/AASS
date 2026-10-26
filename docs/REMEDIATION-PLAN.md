# Installation, security and reliability remediation

## Current evidence and user outcome
The user has Windows, working Docker Desktop/WSL, Python 3.12, and local Ollama
including qwen3.5:9b. Their supplied log proves dependencies, Chromium and real
sandbox isolation passed. A live model API request then failed; API status and
service were hidden in the original message. A later diagnostic ZIP was reported
as a virus by the PC. The exact product/detection is unknown. Do not label it a
false positive, disable protections, rename payloads to evade detection, upload
private data to third parties, or claim antivirus clearance without a real scan.

Goal: a single reviewable release, a double-click setup/start path, reuse of existing
software, clear progress and recoverable errors, bounded agent execution, explicit
cloud connectivity status, and evidence for each claim.

## Phase 1 — Withdraw and inspect
- Remove the reported patch ZIP from current repository distribution and stop
  building partial updater archives. Preserve Git history; no destructive rewrite.
- Inventory source, installer commands, dependency sources, subprocess behavior,
  environment propagation, credential discovery, and archive membership.
- Research Microsoft's SmartScreen/Defender distinction, submission/scan options,
  pip hash checking, and GitHub provenance from official documentation/source.
- Record confirmed findings separately from the unknown antivirus detection.

## Phase 2 — Trust and credential boundaries
- Limit Desktop discovery to predictable .env files and credential folders; keep
  explicit file import and existing environment bindings. Do not inspect arbitrary
  unrelated project files or accept arbitrary AASS_ settings from them.
- Protect API routing: validate provider/endpoint combinations, reject userinfo,
  insecure remote hosts, and unapproved custom judge destinations before requests.
- Strip secret bindings from installer/package/daemon subprocesses. Pass keys only
  to the configured model client. Redact logs and bound their size.
- Audit workspace reads/writes, hardlinks/nonregular files, sandbox snapshots and
  browser network boundaries; repair concrete findings with regression tests.

## Phase 3 — Repeatable installation
- Separate hash-locked runtime dependencies from developer/PostgreSQL test tools.
  Install verified wheels only, with pinned build tools and no isolated implicit
  build dependency downloads. Retain TLS and package/artifact hash verification.
- Use simple batch entry points. No download-and-execute patch, antivirus exclusions,
  execution-policy changes, forced reboot, credential dumps, or opaque executable.
- Retain progress, stage deadlines, safe cancellation and a single installer lock.
- Reuse valid environments; repair missing browser/installation artifacts safely.
  Detect a moved/old installation and support in-place update without another venv.

## Phase 4 — Usability and state
- Distinguish installed, locally verified, cloud unconfigured, cloud rejected,
  and fully verified states. A 401/404/429 must name its service and next action.
- Keep the start menu available for configuration/readiness after local installation;
  task approval still requires passing tests and an independent cloud judge.
- Provide a setup/settings/status path that does not require pasting large scripts.
  Preserve credentials and project files on update. Do not silently switch providers.

## Phase 5 — Release verification
- Build one deterministic source release from explicit files, with per-file SHA-256
  manifest, outer checksum and release metadata. Exclude secrets, state, nested
  archives, virtual environments, bytecode, and executable binaries.
- Add Windows CI for actual batch entry points, regression tests and Microsoft
  Defender custom scan. A missing scanner must be reported, never treated as clean.
- Add dependency vulnerability audit, source security checks and provenance workflow.
  Do not claim code signing without an actual signing identity/certificate.
- Run appropriate Linux unit/integration suites and a clean extracted-release install.
  Record which Windows/Defender/live-provider checks ran and which remain external.

## Acceptance and stop conditions
Implementation is complete only after regression/integration and release checks
pass and reusable instructions are updated. Windows antivirus acceptance and
real provider authentication remain distinct external checks until observed.
A release without a Defender result must be marked unverified, not advertised as
antivirus-cleared. The user's original detection name is optional context, not a
reason to stop independent remediation. Required signing/account credentials are
not invented or requested in chat. Exact unresolved external blockers must be
reported honestly with a short user action.

## Implemented checkpoint
Phases 1–4 are implemented: patch withdrawal, concrete dependency/runtime fixes,
scoped credentials and destinations, hash-locked wheel installation, safer source
and browser boundaries, provider settings menu, and independent install/cloud
states. Local full integration and fresh extracted-runtime checks passed. Phase 5
is implemented as a fail-closed Windows/Linux/security/Defender/provenance release
workflow; actual remote results must be observed before a download is recommended.

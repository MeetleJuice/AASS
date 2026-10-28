# AASS 1.3.1 candidate

Scope: automatic installer-local credentials, explicit first-run cloud consent,
bounded same-provider model checks, saved readiness, protected diagnostic export,
and additional/configurable model-provider routes. See AUTOMATIC-SETUP.md.
Local suite: 470 passed, 3 Windows-only skips before final Windows CI. Bandit
reports no medium/high findings. Provider requests are protocol fixtures, not
live account verification. The attached private file was not committed or sent
to a model provider. Publication remains gated by native Windows installation,
UTF-16 installer-local discovery, shortcut/browser/update checks and Defender.
1.3.0 evidence below is historical and does not establish 1.3.1 readiness.

---

# AASS 1.3.0 published and verified

Published release: https://github.com/MeetleJuice/AASS/releases/tag/v1.3.0-0c1d26c
Download: https://github.com/MeetleJuice/AASS/releases/download/v1.3.0-0c1d26c/AASS-1.3.0.zip
Source revision: 0c1d26c. Verification run:
https://github.com/MeetleJuice/AASS/actions/runs/40604110812 — SUCCESS.

All mandatory Linux, security, Windows regression, BAT, clean managed-runtime,
GUI, custom-icon, production update and Defender gates passed. Publication used
the exact gated artifact. An independent download of the ZIP and six release
assets (ZIP plus five evidence files) passed the matching evidence validator and
matched the clean local build byte for byte. Defender reports zero detections,
including the installed runtime and browser scans. SHA-256:
`b197fe8a237005a4df385950de680e84320f2008084b8c8038ce7afbd97d0ef3`.

The final CI correction explicitly initializes COM around independent shortcut
inspection. Production shortcut persistence uses the Unicode shell interface.
The timeout assertions and oversized-icon payload remain intact; no tests or
release gates were disabled. Local suite: 436 passed, 3 Windows-only skips.

Final acceptance on the user's physical Windows 10 PC, live Ollama generation
and the user's independent cloud account still require the user's first task.
See [the first-task guide](FIRST-TASK.md). No additional features are planned
before that acceptance result. Earlier entries below are historical snapshots.

---

# Latest verification: 24e0a34

Run https://github.com/MeetleJuice/AASS/actions/runs/40603500452 completed with
failure. Security and Linux passed. Windows regressions passed, including the
unchanged timeout assertions and native Unicode shortcut test. The subsequent
"Clean Windows runtime install and real Chromium check" failed; Defender and
publication were skipped. No 1.3.0 readiness or publication is claimed.

Confirmed fixes: f122aee derives breadcrumbs from structured pytest locations and
uses short icon-case IDs without changing payloads/assertions; 24e0a34 persists
shortcut arguments with Unicode IShellLink instead of WScript.Shell's lossy path.
Local full suite: 436 passed, 3 Windows-only skips; focused: 26 passed, 1 skip.

External diagnostic blocker: public clean-install annotations expose only exit1;
full step logs require sign-in and the cloud proxy still denies api.github.com
with CONNECT403. The clean-install failure cause is not established. Obtain the
last60–100 lines of that step from Windows job122537175055 before changing code.
No tests or release gates were disabled. Earlier entries below are historical.

---

# Release readiness

Status as of **October 27, 2026**: **1.3.0 is a release candidate, not a verified
Windows release.** Do not interpret source availability or passing unit tests as
proof that installation will succeed on the destination PC.
This is the pre-publication evidence snapshot. Successful checks and matching
evidence attached to a later published release supersede its pending entries;
user-PC acceptance still requires the user's confirmation.

## What exists

AASS is a bounded Python engineering agent. A local Ollama model proposes one
structured action at a time: inspect a repository, read/write a contained file,
run an approved Python test command, use an explicitly configured browser/MCP
tool, or request completion. There is no separate persisted planning stage.

The supervisor returns observations, intercepts repeated failures, tries bounded
alternative strategies, and stops when limits or service failures prevent
progress. Completion requires nonzero tests after the last write and approval
from an independent cloud model. Changed source and private history stay in the
project when execution stops; source rollback, Git commits and deployment are
not automatic.

The existing 1.3.0 candidate adds a permanent per-user installation, custom
desktop shortcut and in-app update transaction with recovery. These features
still need the Windows release gates below before delivery as a working release.

## Evidence and remaining acceptance

| Check | Evidence / status |
| --- | --- |
| Automated behavior and safety | Full local suite: **435 passed, 3 Windows-only skips** with integrations enabled. Includes worker protocols, scoped files, budgets, review gates, credentials, installer coordination, update transactions and recovery. Passing fixtures do not establish live model quality. |
| Actual Linux services | Integration checks have exercised Docker isolation/testing, Chromium navigation/click/screenshot, official MCP sessions and a disposable PostgreSQL service. |
| Full engineering orchestration | Actual HTTP transport, file writes, Docker test failure, repair, retest and reopened persistent history have been exercised with deterministic worker/judge responses. **Live Ollama plus an actual independent cloud judge: NOT VERIFIED in this environment.** |
| Clean Windows 1.3.0 install/launch | **PENDING.** The release requires native BAT/bootstrap/runtime/Tk/browser checks. |
| Windows 1.3.0 custom icon | **PENDING.** Native COM shortcut creation, redirected Desktop handling and ICO decoding require the Windows gate. |
| Windows 1.3.0 Defender checks | **PENDING.** The exact ZIP and installed runtime/browser payload must pass before publication. |
| Published 1.3.0 package | **PENDING.** No verified 1.3.0 download is promised here. A source ZIP is not its substitute. |
| User's Windows 10 PC | **NOT VERIFIED.** Final acceptance requires the user to install, launch and complete a real task successfully. |

The observed [Windows workflow](https://github.com/MeetleJuice/AASS/actions/runs/40558504707)
reached its maximum duration without supplying the required successful outcome.
That does not identify a particular failing test or prove a desktop-code defect.
The job needs usable runner/test diagnostics and a successful complete rerun;
mandatory checks remain enabled. Further delivery must use the tested release
artifact, not a newly rebuilt or unverified ZIP.

The finalization fixes are committed as `448b445`: rerunning the installer now
recovers an interrupted source replacement before verification, desktop-icon
errors preserve successful local setup, and the CI monitor remains bounded when
its log consumer blocks. The full suite also passed through that process monitor:
435 passed, 3 Windows-only skips, native/wrapper exit 0 and complete output.

The clean package from that revision was independently extracted and installed in
a new permanent test root on Linux. The production same-revision update reused
dependencies and preserved private file/provider selections. A deliberately
broken setup subprocess exited 17; production recovery restored source and the
real runtime, after which Chromium, dependency and manifest checks passed.
These checks did not exercise GitHub download, Windows GUI restart or real model
generation. Candidate ZIP SHA-256:
`39f5b9bf7dc8622e24cad6d9c5f13ffc60f97504645819946b0de2d79b9d6600`.

The [new verification run](https://github.com/MeetleJuice/AASS/actions/runs/40598498697)
has passed Linux and security checks; its Windows result remains pending at this
snapshot. Authenticated diagnostics are currently blocked by the cloud proxy's
CONNECT 403 denial for `api.github.com`. That domain addition is saved in the
cloud-environment draft; saving alone has not enabled access in this runtime.
Public job pages require sign-in for logs and supply no particular failing test.
Do not bypass verification or infer a root cause from the elapsed time.

The previously published
[1.2.1 ZIP](https://github.com/MeetleJuice/AASS/releases/download/v1.2.1-624a13b/AASS-1.2.1.zip)
has historical Windows and scan evidence recorded in [validation](VALIDATION.md).
It predates the new permanent-install/update flow and does not establish 1.3.0
readiness. Its passing CI also does not authenticate the user's Gemini account.

## Practical limits

- Python 3.12 with Tcl/Tk, Docker Desktop's Linux engine and Ollama are prerequisites.
  Windows virtualization changes and restarts may need the machine owner's action.
- No local Ollama daemon or usable independent cloud account is supplied by this
  development environment. The user's own services cannot be tested remotely here.
- The default container includes Python's standard library and `unittest`, not
  arbitrary packages or pytest. Project dependencies need an operator-prepared,
  trusted sandbox image.
- Cloud review is optional during installation but required for approved tasks;
  real requests depend on provider access, quota and billing.
- Browser/MCP configuration is available through the CLI. Those host processes
  do not have the Docker test boundary. This is not unrestricted Windows automation.
- The source distribution is unsigned. Keep antivirus and Windows protections
  enabled; a checksum is not universal antivirus clearance.

Once the release gates pass, use [Windows installation](WINDOWS-INSTALL.md) and
the [first-task walkthrough](FIRST-TASK.md). Do not claim acceptance before the
user confirms the result on their Windows 10 PC.

## Three improvements to consider after acceptance

These are recommendations, not additional work in this release:

1. Add a repeatable live Windows acceptance exercise covering a small failure,
   repair, genuine judge approval, app reopening and an update from the previous
   published version. Protocol fixtures cannot establish that experience.
2. Make optional browser preparation independent of basic Python-task readiness,
   so a browser download problem does not block an unrelated `unittest` task.
3. Show per-action progress and a readable task-history view in the desktop app.
   The present heartbeat/final report and JSON history make troubleshooting harder
   than it needs to be.

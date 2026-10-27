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

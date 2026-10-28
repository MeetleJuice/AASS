# AASS 1.3.1 published and verified

Official ZIP:
https://github.com/MeetleJuice/AASS/releases/download/v1.3.1-97b0d3a/AASS-1.3.1.zip
Source: 97b0d3a. Complete verification:
https://github.com/MeetleJuice/AASS/actions/runs/40610473070 — SUCCESS.

Windows regression, actual BAT, installer-local UTF-16 discovery by reference,
no-consent packaged backend, clean runtime/GUI/browser/icon, production update
and Defender gates passed. Linux real integrations and security checks passed.
The independently downloaded release and all matching evidence validate and the
ZIP matches the clean local build. Defender reports zero detections. SHA-256:
`29c7fa1395352b64aa1c8145f758d1b0cdca3173a77d10b968497f3c367ba605`.

Local suite: 470 passed, 3 Windows-only skips. New provider protocols and automatic
model fallback were exercised with fixtures, not live account credentials. The
uploaded private file was excluded from source, logs, release and API requests.
User-PC API access, quota and the 1.3.1 first task still need destination checks.

For automatic cloud checks, explicitly opt in via
`AASS_SETUP_ALLOW_BILLABLE_CHECK=1` in the private file. Set
`AASS_JUDGE_SERVICE=gemini` (or the intended provider) for a fresh multi-key setup;
a working saved choice is retained. Without consent, use Test connections once.
Custom endpoints require a supported API protocol and explicit destination/key
binding; unknown key names alone cannot establish an arbitrary API contract.
See [automatic setup](AUTOMATIC-SETUP.md) for the policy and supported routes.

Earlier entries below are historical snapshots, not the current verdict.

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

# Current 1.3.0 candidate status

Pre-publication snapshot, October 27, 2026. Later successful checks and matching
evidence attached to a published release supersede the pending release entries.

**Windows release verification is pending.** The clean Windows installation,
custom desktop icon and exact-artifact Defender gates have not supplied the
successful outcome required to publish 1.3.0. The observed
[workflow](https://github.com/MeetleJuice/AASS/actions/runs/40558504707) reached its
maximum duration; no particular test is identified as the cause from that fact.
See [release readiness](RELEASE-READINESS.md) for the acceptance boundaries.

Local verification: **435 passed, 3 Windows-only skips**, with Docker, Chromium,
MCP and PostgreSQL integrations enabled; dependency consistency, Ruff and the
Bandit medium/high gate passed. The full
worker/Docker/review protocol exercise uses deterministic model responses;
**live Ollama plus a real independent cloud judge is NOT VERIFIED here**.
The user's physical Windows 10 PC has not been tested by this environment.

The sections below are dated development/release history, including earlier
states in which Windows CI had not yet run. They do not override this current
1.3.0 verdict or establish acceptance on the user's PC.

---

# Gemini native API correction 1.2.1

Published as [v1.2.1-624a13b](https://github.com/MeetleJuice/AASS/releases/tag/v1.2.1-624a13b).
[Workflow 40375108469](https://github.com/MeetleJuice/AASS/actions/runs/40375108469)
passed Linux, Windows, security and publication. Windows regressions, actual BAT,
clean runtime/Tk/browser checks and Defender archive/installed-payload scans all
passed. Defender reports zero detections. The downloaded public ZIP and evidence
passed the matching evidence validator and reproduced the local clean build:
`832b50e72a74a1ee638a7ab32b7feb006012e0dd6a572568951c96fde44aa0a8`.

An existing extracted 1.2.0 runtime was also updated by overlaying only source
files from the 1.2.1 ZIP. Manifest verification and native Gemini imports passed
through the already-installed runtime, with its private file-selection state
preserved. This patch changes no locked dependencies and needs no new system tool.

A user completed all local installation, package, Docker sandbox, browser and
Ollama checks, then received404 from the cloud judge after Gemini model discovery.
The log lacked the selected model ID, so it does not establish the exact account
or model failure. The code did establish a protocol mismatch: native models.list
capabilities were used to populate a dropdown that called OpenAI-compatible chat.

Gemini judging now uses native generateContent, including generic configurations
that previously pointed at the official /v1beta/openai endpoint. Request IDs,
headers, schema, output limits, legacy migration, blocked/incomplete responses,
failed calls and safe error context are covered without real account credentials.
A discovery-to-connection integration test exercises both actual adapters through
one mock HTTP transport and the same model ID. Local suite: 295 passed, 2 Windows-only
skips. Bandit reports no medium/high finding. Real API entitlement and quota still
require the user's explicit connection test; no live Gemini account success is
claimed from mocked tests. Publication retains actual Windows and Defender gates.

Official protocol references reviewed:
- https://raw.githubusercontent.com/googleapis/python-genai/main/google/genai/models.py
- https://raw.githubusercontent.com/googleapis/python-genai/main/README.md

---

# Guided setup 1.2.0 verification

Observed published release: [v1.2.0-9124d52](https://github.com/MeetleJuice/AASS/releases/tag/v1.2.0-9124d52),
from source `9124d5282c9672183dab304e7ee39b676f674e2b`.
[Workflow 40371471115](https://github.com/MeetleJuice/AASS/actions/runs/40371471115)
passed Linux, Windows, security and publication jobs. The Windows job passed
regression tests (including owned-process tracking), the actual BAT entry point,
clean runtime/Tk window/Chromium checks and Defender archive/payload scans.
The attached report records zero detections, engine1.1.26090.9 and
signatures1.461.140.0. Installed environment and browser scans are both recorded.

The public ZIP and evidence were downloaded independently after publication.
The evidence validator passed; its bytes match the clean local deterministic
build. SHA-256: `9a064102fae2af4be92ed1a44c379a5b93a1c0409dc0f92dda4f197d0034ac34`.
The GitHub latest-release link resolves to this guided setup release. This is
observed evidence for this artifact, not a guarantee for every antivirus engine
or a validation of a user's cloud account.

Local integration run: **240 passed, 2 Windows-only skips**. This includes real
Docker sandbox isolation, PostgreSQL MCP and Chromium checks, model-catalog HTTP
fixtures, credential-file precedence/Notepad encodings, cancellation, and GUI
recovery tests. Ruff and dependency consistency passed. Runtime advisory audit
reported no known vulnerabilities; Bandit reported no medium/high findings.

The actual Tk window was constructed under an isolated X display. A simulated
provider exercised asynchronous key metadata, model selection, worker success,
cloud HTTP404 and successful cloud-only retry. No paid provider request was made.
A full extracted runtime installed its locked wheels and generated its architecture
with a moved private credential-file selection; the cloud configuration error
remained recoverable. Extracted source imports before dependencies are installed.

Windows-specific process tracking, native Tk construction, clean runtime/browser
installation and Defender scans of ZIP/payload are publication gates in
`.github/workflows/verify.yml`. The report attached to each published release
records the exact archive tested. Local or simulated checks do not authenticate
a user's API key, model access or billing quota; use the setup window's explicit
connection test on that machine.

---

# Validation evidence

Validated in the supplied Linux cloud workspace on 2026-10-26 using Python 3.12.14,
Docker Engine 28.4.0 and the machine's installed Chromium.

## Completed checks

Command:

```sh
AASS_INTEGRATION=1 AASS_POSTGRES_INTEGRATION=1 bash scripts/verify.sh
```

Result: **63 passed, 0 failed, 0 errors, 0 skipped** (18.61 seconds).
`pip check`, Ruff lint, Ruff formatting checks and `git diff --check` also passed.
The current-run JUnit result is `generated/verification.xml` (local/ignored).

The suite exercised:

- Hard iteration, total-token and per-call ceilings; request precharging.
- Shell/command rejection; path traversal, hidden credentials and symlink rejection.
- Secret-filtered source snapshots and repeatable bootstrap without telemetry loss.
- Desktop and OneDrive `.env`/credential-text discovery, provider mapping, existing
  binding precedence and actual-model selection, all using temporary test folders.
- Real Docker execution: executable nonzero-count unit tests, read-only workspace
  and root, missing host secrets/socket, disabled outbound network, timeout cleanup
  and bounded output. Temporary task containers were removed.
- Real Chromium: successful loopback-page navigation, selector/coordinate clicks,
  screenshot generation and unauthorized-origin rejection.
- Real official MCP stdio negotiation and allowlisted tool calls.
- Real disposable PostgreSQL: MCP table/row round trip, read-only transactions,
  unauthorized schema rejection and SQL identifier injection resistance. Test
  credentials were ephemeral; database containers were removed.
- Ollama JSON-schema request/response protocol, fresh context, multimodal image
  attachment and bounded response sizes using deterministic HTTP fixtures.
- OpenAI-compatible and Anthropic judge request/response validation using protocol
  fixtures; malformed approvals and inconsistent verdicts fail closed.
- Full worker HTTP protocol -> source changes -> real Docker unit test -> cloud
  review protocol -> approved state, using deterministic model responses.
- Test-evidence invalidation after edits, zero-test rejection, independent review
  rejection, repeated-error strategy pivots, timing normalization, previous-task
  separation, single-writer locking and final approval telemetry.

`bash scripts/setup.sh` completed successfully. Running the launcher installation
again completed without another dependency installation, exercising its fingerprint
marker. Immutable Python and PostgreSQL image digests were verified through Docker
pulls. No tracked source was reset or force-pushed.

## External checks that did not pass

`aass --no-desktop-discovery doctor` exited 2, reporting:

- Docker, immutable sandbox image and Chromium: available.
- Ollama / selected local model: unavailable in this cloud machine.
- Independent cloud judge credentials/model: absent in this cloud machine.

`aass --no-desktop-discovery verify-live` exited 2 with `ConnectError` because no
local Ollama daemon is present. No successful live model generation or independent
premium-model code review is claimed. The model registry was also denied by the
cloud network policy. Your own Desktop, Ollama daemon and credentials are not
accessible from this cloud workspace; automatic discovery must run after download
on your own machine.

Playwright's bundled-browser CDN download was denied by cloud network policy.
The supported installed-system-Chromium fallback was used and functionally tested;
TLS or artifact verification was never disabled. The local launcher can download
Playwright Chromium when the target's network permits it.

## Scope of readiness

The implementation and Linux integration suite are verified. Windows/macOS
launchers are provided but have not been executed on those operating systems.
CI configuration is written but has not run on GitHub. No remote push, public
service, OS service installation, or production deployment has occurred.
LLM-generated tests and independent LLM review do not prove arbitrary programs
correct or secure.

The native application must pass `python launch_aass.py doctor` and
`python launch_aass.py verify-live` on the destination machine with real local
models and your provider credentials before claiming live operation.

## Download artifact verification
The source ZIP was extracted into a separate temporary directory. Its native
launcher successfully installed the locked dependencies into a fresh virtual
environment. The same full integration suite then passed **63 tests, 0 skipped**
in that extracted environment (15.06 seconds). This verifies Linux distribution
installation; it does not establish Windows/macOS or live model readiness.

## Double-click installer update
The updated full Linux suite passed **77 tests, 0 failed, 0 skipped** (22.60
seconds). New coverage exercises subprocess progress and deadlines, credential
redaction, exclusive installation locking, prerequisite reuse, readiness and
live-review failure gates, and the installer's real Docker isolation test.
`Install-AASS.bat` and `Start-AASS.bat` are included in the ZIP. The Windows CI
job now checks the platform-specific coordinator tests and invokes the actual
batch entry point with `--help`. That job has not been observed running here;
full Windows Desktop installation still needs confirmation on the destination.

## Live-connection diagnostics update
A user-provided Windows run confirmed package installation, Chromium downloads,
local Ollama discovery, Docker sandbox isolation and all doctor checks passed.
The final live check returned HTTPStatusError; its service/status were hidden by
the previous generic handler, so live generation and cloud approval remain
unconfirmed from that log.

The CLI now separates local-worker and cloud-judge stages and reports safe HTTP
status/host metadata plus an allowlisted provider code. Tests verify raw request
credentials, response messages and exception bodies are not echoed. The updated
full Linux suite passed **85 tests, 0 failures, 0 skipped** (28.90 seconds).
`Check-Connections.bat` retries only live connections; no package reinstall or
model/image download is needed for that diagnostic.

## 1.1.0 installation/security remediation
The detailed plan is in REMEDIATION-PLAN.md and findings in SECURITY-REVIEW.md.
Local evidence before remote release checks:

- Full Linux run with Docker/browser/MCP/PostgreSQL gates enabled: **109 passed,
  0 failed, 0 skipped** (20.06 seconds).
- pip-audit: runtime, developer and audit-tool locks report no known vulnerabilities
  after the filelock 4.2.1 update. The three previous advisories are recorded in the
  security review; none is assumed to explain the original antivirus warning.
- Bandit medium/high gate: no findings after documented narrow false-positive
  review. Argument-array subprocess low-severity findings remain explicitly reviewed.
- Clean extracted candidate: fresh hash-locked runtime-only installation succeeded.
  Its 38 distributions include pip/project; pytest, ruff, pip-audit and psycopg
  were absent, confirming end-user/developer separation.
- Release manifest verifies after installation; repeated packaging is byte-for-byte
  deterministic. Nested ZIPs, executable binaries, tests, state and venvs are absent.

Windows CI/Defender/publication are separate observable checks. They are configured
to run on the reviewed commit; until their results are observed, no new candidate
is described as Defender-cleared. A cloud account's live authentication/credit is
not validated by CI fixtures and remains a destination-account check.

### Cross-platform lock and browser follow-up
After adding the Windows-only locked wheels, cross-platform closure validation,
all-platform advisory lookup and the isolated browser helper, the full local
Linux integration run passed **113 tests, 0 failed, 0 skipped** (23.95 seconds).
All-platform runtime/development/audit-tool advisory lookups returned no known
vulnerabilities, and the Bandit medium/high gate had no findings/errors. The first
two Windows CI attempts correctly blocked publication at the incomplete dependency
lock; neither is an antivirus clearance. The corrected remote run is the next
required piece of evidence.

## Observed published 1.1.0 release — final evidence

Reviewed source: `5c0182d834c895eac2cc518fc39d8b9afd5b3630`.

- [GitHub run 40349139773](https://github.com/MeetleJuice/AASS/actions/runs/40349139773)
  completed successfully, including Linux integration/security jobs, Windows
  regression/batch checks, clean Windows end-user installation, real Chromium
  through the credential-stripped helper, Defender scan and publication.
- [Published release](https://github.com/MeetleJuice/AASS/releases/tag/v1.1.0-5c0182d)
  includes the exact archive, checksum, Defender report, dependency audit, source
  security report and SBOM.
- [Defender report](https://github.com/MeetleJuice/AASS/releases/download/v1.1.0-5c0182d/defender-scan.json):
  `passed=true`, archive/payload exit codes both 0, **0 detections**, installed
  environment and browser bundle both scanned. Engine `1.1.26090.9`, signatures
  `1.461.140.0`; the Microsoft scanner signature was valid.
- Archive SHA-256:
  `08cc3af6be488f2f86b83d910fc6f7dac3418086f64fd650671e0195f8c8e9a4`.
  The downloaded public GitHub asset matched its checksum and scan report; the
  local evidence checker accepted all matching reports and manifest metadata.
- Rebuilding the clean tagged source locally on Linux produced **identical ZIP
  bytes** to the Windows-built published archive. The 43 runtime-file manifest
  identifies the clean source revision above.
- [GitHub provenance](https://github.com/MeetleJuice/AASS/attestations/59975537)
  and its public Sigstore bundle are available. The installed local gh 2.46 has
  no attestation subcommand, so independent local cryptographic verification with
  gh was not claimed; modern gh can verify the public attestation.

These are actual observed results, not presumed from workflow configuration.
They do not classify the old unknown warning as a false positive or guarantee
acceptance by every antivirus/reputation system. Source remains unsigned for
Windows Authenticode. Destination account/model availability, live generation
and cloud API credits must still be checked through the application menu; CI
contains no personal model credentials.

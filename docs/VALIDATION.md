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

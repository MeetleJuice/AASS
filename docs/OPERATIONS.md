# AASS operations

## Installation and updates
Windows: use the full verified GitHub release and double-click Install-AASS.bat.
Use Start-AASS.bat for later launches. [Windows instructions](WINDOWS-INSTALL.md)
cover credentials, provider choice, recovery, status and security warnings.

Linux/macOS development requires Python 3.12, Docker and Ollama. Existing checkouts
are isolated task workspaces; do not create another worktree unless requested.
Run `bash scripts/setup.sh` for the developer environment, or use the release
launcher for runtime dependencies only. No platform is certified solely because
the shared Python tests passed elsewhere. Windows CI and Defender results are
separate observable evidence.

The runtime lock contains exact SHA-256 wheel hashes and pinned build tools.
Installation uses `--require-hashes --only-binary=:all:`. The reviewed source is
installed with `--no-deps --no-build-isolation`; no implicit build dependencies are
fetched. On a changed fingerprint, wheels are reinstalled from verified artifacts
instead of trusting an old installed version number. Development/PostgreSQL and
security-audit tools have separate locks and are not part of end-user setup.

## Models and settings
Ollama defaults to loopback port 11434. The installed model list is checked;
qwen3.5:9b is preferred, then another installed Qwen, then an available model.
AASS_WORKER_MODEL is explicit. A remote OLLAMA_HOST requires HTTPS without
userinfo/query/path; local loopback HTTP is allowed. Vision actions require a
vision-capable selected worker.

Environment bindings and recognised private file settings are imported without
executing shell text. Fixed app-local .env/.env.txt files are supported before the bounded Desktop
search. Automatic discovery is limited as documented in the Windows
guide. For another private file use the window's credential-file picker or the CLI's
`--credentials-file` option. App-local private files are ignored by Git and
excluded from releases. Never put real keys in target projects or commits.

Official judge hosts are api.openai.com, generativelanguage.googleapis.com and
api.anthropic.com. HTTPS and provider-adapter compatibility are validated before
requests. To use a trusted custom HTTPS model gateway, set AASS_ALLOWED_JUDGE_HOSTS
explicitly in the parent process environment, plus AASS_JUDGE_BASE_URL/model/key.
That destination allowlist cannot be imported from Desktop files. Never approve
a host you do not intend to receive your key and source. AASS_JUDGE_PROVIDER is
`anthropic` for Anthropic Messages and `openai` for OpenAI-compatible endpoints.

The window stores a provider/model preference without a key and loads model IDs
from official provider catalogs. Metadata lookup does not establish generation
access or quota; Test connections performs actual requests. The advanced CLI
supports auto/openai/gemini/anthropic and explicit model overrides. Provider
conflicts fail before credential transmission. GUI startup never makes paid calls.

## Native CLI
From an installed Windows folder use `.venv/Scripts/python.exe -m orchestration_canvas`;
on Linux use `.venv/bin/aass` or `.venv/bin/python -m orchestration_canvas`.

```sh
aass doctor
aass verify-live
aass run --workspace /absolute/path/to/separate/project --task "Implement addition with unit tests"
aass status --workspace /absolute/path/to/separate/project
```

`doctor` checks local capabilities and configuration presence/validity; it does
not authenticate the cloud account. `verify-live` makes real requests and can
incur API charges. Paid verification is not required for package installation.
HTTP diagnostics contain service/status/host and recognised provider codes, never
raw error bodies or authorization headers.

Run a new supervisor for each task. A single-writer lock protects target state.
Source edits persist after interruption; they are not committed/pushed/rolled back
automatically. Tests after the last write must have a nonzero count, and a strict
independent verdict must approve before a task reports success. Empty test runs,
compilation-only checks, malformed verdicts, issues and service errors cannot
approve. Budgets cap each run at 20 iterations and 64,000 conservative token
reservations, charging failed calls too; these are not account-wide dollar limits.

## Isolation and supported workflows
The worker can read regular contained files and replace contained source files
atomically. Hidden/runtime/credential-like paths and symlinks are denied; reads
and snapshots reject hardlinks and nonregular files. The executing runtime must
be outside the target project. Docker tests run over a filtered read-only source
snapshot: no host secrets/socket, no network, dropped capabilities, read-only root,
512 MiB RAM, one CPU, 64 processes, bounded time/output. Docker shares the kernel;
it is not a micro-VM. Only approved Python test/compile argv prefixes are accepted.

The default pinned Python image has unittest, not your project's dependencies.
Build a trusted image with pinned project dependencies and set AASS_SANDBOX_IMAGE
explicitly to its immutable digest when needed. No runtime package download or
host-shell fallback exists inside a worker test. Tests write scratch data under
/tmp; the source mount stays immutable. This runtime is for Python engineering
workflows; other languages need explicit tools/images/policies.

## Browser and MCP
Browser origins are explicitly authorised with `--browser-origin`. HTTP request
routing blocks other origins; WebSockets, service workers and downloads are
blocked. Screenshots are local worker inputs, size-limited and charged against
the request budget; large images can trip the budget. Playwright implements this
capability; no OSWorld service is bundled. Browser processes run on the host.

MCP uses the official SDK with `--mcp-config /private/path/server.json`. Only
operator-trusted stdio programs or approved HTTPS servers and listed tools are
available. Stdio is a host process, not a container. Only listed environment
names are passed; OAuth login is not implemented. Inputs/returned context and
call duration are bounded. See examples/ in the development source.

For the optional PostgreSQL driver, run `python launch_aass.py --install-only --postgres`;
this uses requirements-postgres.lock with runtime plus the two driver wheels,
not the developer tool set. The PostgreSQL MCP server uses AASS_POSTGRES_DSN and an allowlisted
AASS_POSTGRES_SCHEMAS. Use a least-privilege read-only role and verified TLS for
remote databases. Fixed list/read tools quote identifiers, cap rows and use
read-only transactions/statement timeouts; no arbitrary SQL tool is exposed.
Only authorise data you permit the local model to read.

## Test and release process

```sh
AASS_INTEGRATION=1 AASS_POSTGRES_INTEGRATION=1 bash scripts/verify.sh
python scripts/package.py
```

Developer setup installs requirements-dev.lock. Security tools use the separate
requirements-audit.lock. Integration tests use disposable containers and generated
test-only credentials; no production database key is required. JUnit output belongs
to the current run in generated/. Gated unrun integrations are reported as skips.

Only a clean Git revision can build a normal release. The explicit release manifest
excludes venvs, secrets, state, tests, dev scripts, nested ZIPs and executable
binaries. Package bytes are deterministic across normalised line endings. A dirty
local candidate cannot pass publication checks. Windows scans archive and extracted
payload using Microsoft Defender; successful matching scan, dependency/source
checks, Windows/Linux tests and GitHub provenance gate publication. Missing scan
capability blocks release instead of pretending it passed. See SECURITY-REVIEW.md.

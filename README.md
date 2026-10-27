# AASS — Autonomous Agent System Stack

A bounded Python engineering agent with a local Ollama worker, isolated
Docker tests, persistent failure history, and an independent cloud review gate.
Preferred local model: **qwen3.5:9b**. Current version: **1.3.0**, with guided Windows setup.

## Windows installation

Use the ZIP from **[GitHub Releases](https://github.com/MeetleJuice/AASS/releases)**,
not an old diagnostic patch. An approved release includes its exact Microsoft
Defender scan report, SHA-256 checksum, dependency audit, source scan, SBOM and
GitHub build attestation. A release is published only after those checks succeed.

1. Extract the full ZIP into a new Desktop folder and double-click **Install-AASS.bat**.
2. Setup checks the latest verified release and installs AASS in your permanent
   per-user application folder. Existing Docker, Ollama and models are reused.
3. After local checks pass, your desktop gets a custom **AASS** icon. Choose your
   private credential file/provider/model in the setup window and test connections.
4. Launch from the desktop icon. Use **Update** in the app for future GitHub releases;
   it verifies, installs, checks and restarts automatically, preserving settings.

Updates use published, verified releases. GitHub Code ZIP installs fetch that
verified release automatically. Failed updates restore the previous app/runtime.
See the [install/update plan](docs/INSTALL-UPDATE-PLAN.md).

Your machine needs Python 3.12 including Tcl/Tk, Linux-container Docker Desktop and Ollama. Setup
starts installed services. New system-wide prerequisites are installed only with
an explicit `--install-prerequisites` option. Windows feature changes/reboots and
API account billing still require the owner of the machine/account.

Installation does not make paid cloud requests by default. A final task still
requires nonzero-count tests after the last write and an independent judge's
approval. No missing credential or failed request can become an approved task.

## Security and credentials

A user reported an antivirus warning for the previous patch ZIP. That artifact
was withdrawn. The detection name is unknown; it has not been declared a false
positive. **Do not disable antivirus, add exclusions or restore a quarantined
patch.** Hashes and provenance establish integrity/origin, not universal safety.
Unsigned source is not an Authenticode-signed Windows application.

Existing environment bindings take precedence. Choose an existing private file
in the window, or use automatic discovery from app-local `.env`/`.env.txt`, Desktop
`.env` and bounded credential folders, not arbitrary unrelated Desktop projects.
Recognized cloud keys are `OPENAI_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`, and
`ANTHROPIC_API_KEY`, or the explicit `AASS_JUDGE_API_KEY`/`AASS_JUDGE_MODEL` pair.
The window saves only the selected file path and provider/model preference;
keys stay in your private file or environment. Official API endpoints are validated before keys are sent.
A trusted custom HTTPS provider requires an explicit environment allowlist.

The cloud judge receives the task, changed code and test evidence. Only use it
for source you permit that provider to receive. Local browser screenshots remain
local model inputs. Keep secrets outside engineering target projects.

## The five layers

| Layer | Implemented responsibilities |
| --- | --- |
| Infrastructure & safety | Hard token/iteration ceilings; command policy; disposable networkless Docker tests with resource/output limits |
| Connectivity | Official MCP sessions and tool allowlists; read-only PostgreSQL tools; Git/import mapping |
| Execution | Fresh-context schema-validated Ollama actions; scoped atomic file edits; origin-scoped Playwright tools |
| Quality | Atomic trajectory, repeated-failure intercept, bounded strategy pivots and strict independent verdicts |
| Executive canvas | Single-writer supervisor, private state, native CLI and guided graphical setup/task window |

Containers share the host kernel; they are not micro-VMs. Browser and trusted MCP
server processes run on the host. The first runtime supports bounded Python test
workflows, not unrestricted OS automation. Generated tests and LLM review do not
prove arbitrary software correct or production safe.

## Development and evidence

```sh
bash scripts/setup.sh
AASS_INTEGRATION=1 AASS_POSTGRES_INTEGRATION=1 bash scripts/verify.sh
```

Runtime wheels and build tools have exact versions and SHA-256 hashes. Developer,
PostgreSQL test and audit tools have separate locks; end-user setup does not
install them. TLS and artifact verification remain enabled.

- [Windows instructions](docs/WINDOWS-INSTALL.md)
- [Operations](docs/OPERATIONS.md)
- [Architecture and trust boundaries](docs/ARCHITECTURE.md)
- [Remediation plan](docs/REMEDIATION-PLAN.md)
- [Security review and research](docs/SECURITY-REVIEW.md)
- [Validation evidence](docs/VALIDATION.md)
- [Release notes](docs/RELEASE-NOTES.md)

See the [setup simplification plan](docs/SETUP-SIMPLIFICATION-PLAN.md) for the
installation problems addressed and acceptance checks.

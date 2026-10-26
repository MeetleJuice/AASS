# AASS — Autonomous Agent System Stack

A bounded, headless Python engineering agent with a local Ollama worker, isolated
Docker tests, persistent failure history, and an independent cloud review gate.
Preferred local model: **qwen3.5:9b**. Current maintenance version: **1.1.0**.

## Windows installation

Use the ZIP from **[GitHub Releases](https://github.com/MeetleJuice/AASS/releases)**,
not an old diagnostic patch. An approved release includes its exact Microsoft
Defender scan report, SHA-256 checksum, dependency audit, source scan, SBOM and
GitHub build attestation. A release is published only after those checks succeed.

1. Extract the complete release ZIP.
2. Double-click **Install-AASS.bat**. Existing Python, Docker, Ollama and models are
   reused. Local setup has visible stages, deadlines and a log.
3. The menu opens after local setup. Choose **cloud provider**, then **check model
   connections**. A provider/account error does not require reinstalling software.
4. Use **Start-AASS.bat** for later launches; choose a separate project and task.

Your machine needs Python 3.12, Linux-container Docker Desktop and Ollama. Setup
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

Existing environment bindings take precedence. Automatic discovery reads Desktop
`.env` and bounded credential folders, not arbitrary unrelated Desktop projects.
Recognized cloud keys are `OPENAI_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`, and
`ANTHROPIC_API_KEY`, or the explicit `AASS_JUDGE_API_KEY`/`AASS_JUDGE_MODEL` pair.
The menu stores only your provider/model preference; keys stay in your private
file or environment. Official API endpoints are validated before keys are sent.
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
| Executive canvas | Single-writer supervisor, private state, native CLI and local project/task menu |

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

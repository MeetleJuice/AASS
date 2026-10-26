# AASS 1.0 implementation plan

## Contract
Preserve the README's headless dual-loop architecture, preferred `qwen3.5:9b`
local worker, independent cloud review, bounded execution, and persistent trajectory.
Use Python 3.12+, Docker isolation and explicit credentials supplied by environment
or automatically discovered Desktop .env/credential-text files, as requested by the user. Never persist secret values in the
architecture specification. Existing checkouts are already isolated development
workspaces; no additional worktree is required.

## Sequential delivery
1. Bootstrap: generate the original build matrix without overwriting runtime state;
   discover actual Ollama models; automatically import recognized Desktop settings and support an explicit credentials file.
2. Layer 1: hard token/iteration budgets, command policy, ephemeral networkless Docker
   containers, time/memory/process/output limits, and path containment.
3. Layer 2: official MCP SDK sessions, explicit server registration and tool allowlists;
   bounded Git file/dependency mapping without exporting credentials.
4. Layer 3: fresh-context structured Ollama actions; scoped file tools and isolated
   test execution; Playwright screenshots, coordinate and selector interactions.
5. Layer 4: atomic trajectory persistence, seeded three-event fixation detection,
   forced strategy pivots, and independent cloud judge with fail-closed verdicts.
6. Layer 5: bounded CRDAL state machine, executable headless CLI, state canvas,
   final review gate, and diagnosis commands.
7. Automated unit, integration and failure-path tests; Docker and browser smoke
   checks; install/verification scripts and CI; document actual live-service limits.

## Acceptance
Local tests must exercise real tool execution and failure handling. Doctor must
report missing external services as unavailable, not substitute fake success.
A task is completed only after a strict independent judge approval. No production
readiness claim without live worker, judge, browser and sandbox checks. A mock HTTP
server validates protocols in tests but is not live model validation.

## References consulted
- Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md
  (`/api/tags`, `/api/chat`, JSON schema format, usage counters).
- MCP official Python SDK: https://github.com/modelcontextprotocol/python-sdk
  (`ClientSession`, stdio client and Streamable HTTP transport).
- Playwright Python: https://github.com/microsoft/playwright-python
  (Chromium installation and synchronous browser contexts).
- Docker run: https://docs.docker.com/reference/cli/docker/container/run/
  (read-only root, resource limits, capabilities and network isolation).

## Deployment boundary
This cloud machine is not the user's Desktop. Desktop discovery runs automatically on the destination and can be disabled; existing environment bindings take precedence.
No cloud API key is bundled. Production target/hostname was not supplied: provide
native CLI execution and a deployment runbook rather than invent a destination.


## Delivery status
All five implementation layers and automated setup/verification are written.
The Linux suite passed 63 tests including Docker, browser, MCP and PostgreSQL
integration. See VALIDATION.md for exact commands, external-service failures and
remaining destination-machine checks. A source ZIP and native launchers are
provided; live local model execution and independent cloud review remain pending
on the user's own machine rather than being represented as completed here.

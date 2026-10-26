# AASS 1.2.0 — guided setup and model discovery

Double-click Install-AASS.bat to open one graphical setup window. It reuses local
tools, displays progress and offers cancellation. Choose an existing private
credential file, select a provider and pick an actual returned text model from its
catalog. App-local .env/.env.txt and BOM-marked Notepad UTF-16 files are supported.
Only the selected path and provider/model preferences are saved.

Local installation makes no paid cloud requests. Explicit connection tests report
authentication, access, missing-model and quota errors in the same window. A
successful worker check is retained while retrying the cloud judge. Run a task
using a folder picker and task field; task tests and independent approval remain
mandatory. Advanced CLI and the legacy terminal menu remain available.

Publication requires Linux/Windows verification, actual Windows GUI construction,
hash-locked runtime/browser installation, dependency/source checks and matching
Microsoft Defender scans of the archive and installed payload. Inspect the exact
release's attached scan report and SHA256SUMS; source remains unsigned. Windows
virtualization/restarts and API account billing/access still require the owner.

---

# AASS 1.1.0 — reviewed installation and distribution

This source release replaces the withdrawn diagnostic patch distribution.
Extract the complete ZIP and double-click Install-AASS.bat. Existing Docker,
Ollama and models are reused. Local installation and cloud account verification
are separate; use the menu to choose your provider and check connections.

Runtime packages/build tools are hash-locked; known filelock advisories were
fixed. Credential access/routing and subprocess environment boundaries were
restricted. Atomic workspace edits, nonregular-file/hardlink checks and browser
WebSocket restrictions address concrete audit findings.

The release is accompanied by its exact Microsoft Defender report, SHA256SUMS,
dependency audit, source security report, SBOM and GitHub build attestation. These
are integrity/scan evidence, not an Authenticode publisher signature or a promise
that all security products accept the source. Do not disable Windows protection
if another warning appears. The original detection name remains unknown.

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

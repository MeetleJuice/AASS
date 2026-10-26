# Windows — one release, two double-click entry points

## Download and first launch

Use the full **AASS 1.1.0 release ZIP** from the repository's GitHub Releases
page. A published release has passed the release workflow and includes its
Microsoft Defender scan report, SHA256SUMS, dependency audit, source scan, SBOM
and GitHub attestation. Do not use the withdrawn connection-check patch.

1. Extract all release files. Do not run from inside File Explorer's ZIP viewer.
2. Double-click **Install-AASS.bat**.
3. Leave the window open. You see each stage, installer output, a heartbeat and
   bounded retries. The local task menu opens when local installation completes.
4. Choose **cloud provider** if multiple keys are available or settings conflict.
5. Choose **check model connections** when ready to make real, potentially paid
   API requests. These checks are separate from package installation.
6. Later use **Start-AASS.bat**. It also verifies the release file manifest.

A release manifest detects changed/missing runtime files; a checksum is not an
antivirus verdict or a publisher signature. The stdlib verifier is started in
isolated mode before application imports. Local `.venv`, `.aass`, generated
outputs and developer files are excluded from runtime-file integrity checks.

## Your existing machine

Python 3.12, Docker Desktop with a Linux engine, and Ollama are prerequisites.
Existing installations, models and cached image downloads are reused. Setup
starts installed services. It prefers installed qwen3.5:9b, honours an explicit
AASS_WORKER_MODEL and never replaces another installed model just to choose it.
If no model is present, setup explains/downloads the selected workhorse.

New system prerequisites require an explicit `--install-prerequisites` option;
there is no silent cascade of installers. Docker may require a Windows feature,
WSL setup, virtualization support, administrator approval or a restart. Complete
that Windows/Docker action and rerun the BAT. AASS never forces reboot, changes
firmware, changes execution policy or disables antivirus/TLS verification.

## Credentials and provider selection

Automatic import reads Desktop `.env` and named key/API/token/credential folders
(up to one nested directory, bounded to 100 files). It does not open unrelated
Desktop projects' `.env` files. Existing process bindings take precedence. Only
recognized settings/key names are imported; executable paths and custom API host
approval cannot be imported from those files.

Supported cloud names: OPENAI_API_KEY; GEMINI_API_KEY/GOOGLE_API_KEY;
ANTHROPIC_API_KEY; or AASS_JUDGE_API_KEY with AASS_JUDGE_MODEL. Values stay private
in your file/environment. The menu stores only provider/model preference in
`.aass/provider.json`. Selecting Gemini explicitly uses the Gemini binding even
when an OpenAI key is also present. Providers do not silently fall back to each
other. A model override can be entered for your account's available model.

The judge receives your engineering task, changed source and test evidence. Use
an account/provider that may receive that code. Setup makes no paid requests by
default. A task cannot report approval without the independent judge gate.

## Status and recovery

- Local prerequisites/packages/browser/sandbox failures: setup reports the stage
  and returns an error; fix that local prerequisite and rerun.
- Local installation complete, no judge configuration: menu remains available;
  choose provider/add the named key in your private file, then check connections.
- Model API 401: rejected authentication. 403: denied permission/model access.
  404: wrong/unavailable endpoint or model. 429: rate/quota limit; a reported
  `insufficient_quota` specifically needs usable API credits/quota.
- Cloud errors are configuration/account state, not a reason to reinstall Docker,
  Python or all packages. An app subscription may not include API credit.
- A successful local installation is distinct from live worker/cloud verification.
  Only successful live checks mark the installation fully verified.

AASS logs known-key-redacted stage output to `.aass/setup-<timestamp>.log` and
writes `.aass/setup-status.json`. Logs are bounded. Only designated model-client
subprocesses receive API key bindings; installer, package and daemon children do
not. Share the relevant stage/status/hint, not secrets or an environment dump.

On a reviewed in-place update, managed source is replaced, the changed dependency
fingerprint triggers hash-verified runtime wheel reinstall, and models/credentials
are retained. An exact known obsolete Check-Connections.bat may be retired; an
unknown/user-modified helper is preserved and reported for review.

## Security warnings

If Windows still reports a threat, stop and keep protection enabled. Do not add
an exclusion, restore a quarantined patch or click through a malware warning.
Windows Security > Virus & threat protection > Protection history can identify
the detection. SmartScreen reputation/publisher prompts and antivirus detections
are different mechanisms; the original warning is unclassified. This is unsigned
source; no Authenticode certificate or universal antivirus acceptance is claimed.

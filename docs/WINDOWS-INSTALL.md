# Windows installation and updates

1. Download the full ZIP and extract it into a new Desktop folder.
2. Double-click **Install-AASS.bat** and keep the progress window open.
3. Setup checks GitHub, installs AASS permanently, prepares local tools and creates
   your custom **AASS** desktop icon after local checks pass.
4. If asked, select your existing private `.env` / `.env.txt` file. Choose the
   provider/model and use **Test connections** when ready for real API requests.
5. From then on, launch with the desktop icon. Click **Update** in AASS for updates.

No PowerShell commands or manual copying of future update files are needed.
The permanent application folder is `%LOCALAPPDATA%/Programs/AASS`.

## What setup prepares

Python 3.12 including Tcl/Tk, Docker Desktop with a running Linux engine, and
Ollama are prerequisites. Existing installations, downloaded models and cached
images are reused. Setup installs hash-locked application dependencies, verifies
the browser and real sandbox execution, then creates the desktop shortcut on your
actual Desktop, including OneDrive redirection. Dependencies and source are
prepared in the permanent folder; built virtual environments are never relocated.

If Docker requests Virtual Machine Platform, WSL, virtualization or a Windows
restart, complete that Windows action using Docker's official instructions. Save
work and restart Windows when requested, then retry setup. AASS does not change
firmware, force restarts or weaken Windows protection. Missing system tools are
reported; advanced `--install-prerequisites` allows supported official winget
installations explicitly. Local package setup makes no paid model calls.

## Private credentials

A `.env` or Notepad `.env.txt` beside the extracted installer is recognized and
bound by absolute path. You can also choose another existing file in the window.
Use KEY=value lines; UTF-8 and BOM-marked Notepad UTF-16 are supported. Supported
names include GEMINI_API_KEY / GOOGLE_API_KEY, OPENAI_API_KEY and ANTHROPIC_API_KEY.
Only the selected path and provider/model preference are saved; values stay in
your private file. Keep that file in place or select its new location after moving
it. Never commit keys or paste them into chat.

Process bindings take precedence, then selected-file settings and bounded Desktop
discovery. Unreadable explicit selections are reported. Listing models uses an
official HTTPS metadata endpoint and does not prove generation access or quota.
Gemini uses native generateContent; older official compatibility URLs migrate in
memory. Connection tests and tasks make real, potentially paid requests.

## Updates

**Update** downloads a complete published release from MeetleJuice/AASS. It checks
archive hashes, the clean source manifest and matching Defender/audit evidence.
It then closes the GUI, saves source/runtime for rollback, applies the release,
installs needed changes, checks runtime/GUI/browser operation, refreshes the
shortcut and restarts. Settings and separate projects remain. Source-only updates
reuse dependencies; changed dependency locks trigger hash-verified installation.

Failed updates restore both source and runtime. If interrupted, the desktop
launcher loads the complete verified backup engine before importing potentially
incomplete application modules. Reopening AASS shows update/recovery status.
The progress window describes each stage. Only one GUI/update can own an install;
close any manually launched CLI processes before updating.

The latest published verified release is used, rather than untested branch code.
GitHub Code ZIPs automatically fetch it. If main is newer than the published
version, wait for publication and rerun. Offline installation is an advanced
option requiring a complete manifest-verified release.

## Recover from connection problems

Your local installation remains installed when a cloud check fails. A successful
worker check is retained for a cloud-only retry. Logs identify provider, model,
API route and recognized machine-readable error codes without raw responses.

- 401 / invalid key: choose the current private key file and refresh detection.
- 403 / restrictions: check API/project permissions and allowed key restrictions.
- 404: select another listed text model; it may lack access on this API account.
- 429 / billing: check API usage, credits, quota and rate limits before retrying.
- Timeout: check the network/service and retry that check.

No reinstall is needed for provider account errors. App subscriptions may not
include API credit. The independent judge receives task, changed source and test
evidence. Use an account authorized to receive that code.

## Release evidence and logs

Published releases include SHA256SUMS, Defender archive/installed-payload results,
a dependency audit, source scan, SBOM and GitHub build provenance. Windows CI
checks managed bootstrap, actual GUI/runtime/browser, COM shortcut and ICO decode.
A checksum proves integrity, not universal antivirus acceptance. Source remains
unsigned. Keep protection enabled; inspect Protection history if a threat is
reported. Do not add exclusions or restore the withdrawn diagnostic patch.

Application status/logs, update plans and the latest rollback copy live in `.aass`
inside the permanent installation. Share sanitized stage/status messages, never
private credential files or environment dumps. The native CLI remains available
for advanced automation. See [install/update plan](INSTALL-UPDATE-PLAN.md).

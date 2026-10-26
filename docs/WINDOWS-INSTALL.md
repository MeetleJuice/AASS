# Windows: extract, double-click, start

You do not need to paste commands into PowerShell.

1. Download the current ZIP and extract **all** files into a new folder.
2. Double-click **Install-AASS.bat**. Keep its window open and accept any legitimate
   Windows installer permission prompts.
3. If setup passes, the task menu opens automatically. Choose **Run a task**,
   enter a separate project folder, and describe what you want built.
4. Later, double-click **Start-AASS.bat** to reopen the menu.

Read `INSTALL-FIRST.txt` in the ZIP if you are unsure which file to open.

## Automatic stages
- Find Python 3.12; install the official winget package if it is missing.
- Find Docker Desktop and start it if its Linux engine is stopped. Install the
  official package if missing. Reuse your existing installation and image cache.
- Detect the configured Ollama service; start installed local Ollama if necessary.
  Prefer your installed `qwen3.5:9b`; preserve an explicit model override. Reuse
  other installed worker models or pull the selected model if none is available.
- Discover supported credentials in Desktop and OneDrive Desktop .env files and
  credential-folder text files, with existing process settings taking precedence.
- Prepare the pinned sandbox image, locked Python dependencies and Chromium.
- Verify dependencies, run a real container isolation test, test Chromium and
  detect the worker and judge settings.
- Send a live worker request and independent cloud verification request. These
  final checks may incur charges with your cloud provider.
- Write a final status and launch the local task menu after successful setup.

Each long-running installer stage prints a heartbeat every 15 seconds and has a
finite timeout. A heartbeat confirms the process is still running, not that its
network download is advancing. Failures stay visible; the batch window pauses
instead of disappearing. A rerun reuses installed dependencies and cached model
and container downloads. It never deletes or overwrites your Desktop .env files.

## Windows or account actions that cannot be automated here
If Docker reports a missing Windows feature, virtualization setting, WSL setup,
or required restart, complete the Windows/Docker prompt and run the BAT again.
The installer does not force a restart, change firmware settings or disable TLS.
Winget may need an administrator permission prompt. It does not install an
unsigned substitute if verification fails.

If no supported cloud credentials are found, setup records
`installed_needs_configuration` and explains the accepted variable names. It
cannot invent your key or account access. Your private file needs
`OPENAI_API_KEY`, `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`, or the explicit
`AASS_JUDGE_API_KEY` and `AASS_JUDGE_MODEL` pair. Keep actual values private.
No credentials are bundled, printed or submitted in command arguments.

## Logs and status
The hidden `.aass` folder inside the extracted application contains:

- `setup-<timestamp>.log`: stage output with known credential values redacted.
- `setup-status.json`: installing, blocked, installed-needs-configuration,
  installed-live-unverified, cancelled, or ready status.
- `setup.lock`: prevents two installers from running against this folder.

The menu can display the last installation status. If you need help, share the
last relevant error lines with any sensitive information removed. Do not send
credentials or an environment dump.

## Validation limits
The installer coordinator is exercised on Linux with real subprocesses and
Docker, plus simulated prerequisite/readiness responses. The Windows CI job is
configured to exercise its batch entry point and platform-specific locking; a
successful Windows CI run is a separate result, not assumed from its existence.
The full Docker Desktop UI and reboot flow still need the destination machine.

For unattended development checks, `python install_aass.py --skip-live` explicitly
skips paid model verification and records `installed_live_unverified`. It does not
claim full readiness. `AASS_PYTHON` may select a known Python 3.12 executable for
the batch bootstrap in automated Windows tests.

## A model API rejects the final connection check
An HTTP error after package/browser/sandbox checks means the installation has
reached a model service, which rejected a request. Credential discovery proves
presence, not successful authentication or available account credit.

Double-click **Check-Connections.bat** in the installed application folder. It
prints whether `ollama_worker` or `cloud_judge` failed, the HTTP status, API hostname,
a recognized provider error code when available, and a specific next step.
It never prints raw API messages, authorization headers or complete request URLs.
For example, HTTP 401 indicates rejected authentication, 404 an unavailable model
or endpoint, and 429 a rate/quota limit; `insufficient_quota` specifically indicates
account credit/quota. Do not replace keys, change models or reinstall services
until the reported service/status identifies the actual failing prerequisite.

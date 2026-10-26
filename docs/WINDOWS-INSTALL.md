# Windows — guided setup

Download the full **AASS 1.2.0 release ZIP** from
[GitHub Releases](https://github.com/MeetleJuice/AASS/releases/latest). Extract all
files, then double-click **Install-AASS.bat**. No PowerShell folder navigation is
needed. Keep Docker Desktop open with its Linux engine running.

The setup window prepares local tools, shows progress, detects your private key
file and loads a model dropdown from your provider. If more than one provider has
keys, choose the one you intend to use. Click **Test connections (uses API)** when
ready, then use the **Run a task** tab to browse to a separate project folder and
describe your task. Later double-click **Start-AASS.bat** for the same window.

## Credentials without commands

Your existing `.env` or Notepad `.env.txt` beside Install-AASS.bat is recognized.
Alternatively, click **Choose existing .env / text file** and select your private
file wherever you keep it. Only its path is saved in `.aass/credentials.json`;
key values stay in the file. UTF-8 and BOM-marked UTF-16 text are supported.
Use simple `KEY=value` lines. Supported names are `GEMINI_API_KEY` or
`GOOGLE_API_KEY`, `OPENAI_API_KEY`, and `ANTHROPIC_API_KEY`.

Existing process environment bindings take precedence, followed by your explicitly
selected file, application `.env`, application `.env.txt`, and bounded Desktop
credential discovery. The Desktop search reads `.env` and named key/API/token/
credential folders, at most one nested directory and 100 files. It does not scan
unrelated Desktop projects. An unreadable explicit selection is reported, rather
than silently replaced by another credential. Never paste keys into chat.

The model list uses official HTTPS endpoints. It makes no generation request;
being listed does not guarantee model access, billing entitlement or quota.
Choose a listed text model, then test it. Provider/model preferences are saved in
`.aass/provider.json`, without keys. An unavailable saved model is replaced only
by an ID actually returned in the catalog. Providers never silently switch to
another account. The advanced generic `AASS_JUDGE_API_KEY` needs its matching
`AASS_JUDGE_BASE_URL` so setup can identify the intended provider safely.

## Local prerequisites and progress

Python 3.12 (including Tcl/Tk), Docker Desktop with a Linux engine and Ollama are
required. Existing installations, downloaded models and cached images are reused.
The installer starts installed services, prefers qwen3.5:9b if present and reuses
another installed model rather than replacing it. Missing system prerequisites
are reported. The advanced CLI `--install-prerequisites` option explicitly allows
supported official winget installers; normal setup does not silently chain them.

Downloads show stages, output and a regular elapsed-time message. You can cancel
the current operation. Completed stages can be reused on retry. Large models and
browser downloads can take several minutes depending on your connection.

If Docker reports **Virtual Machine Platform**, **WSL**, virtualization or restart
requirements, use **Docker / Windows help** in AASS. Complete the Windows action
in Docker's official instructions and restart Windows when requested. Restarting
only Docker is insufficient. Then reopen AASS and click Prepare / check this PC.
AASS does not force a reboot, alter firmware, change execution policy or weaken
Windows protection.

## Recover from a cloud error in the same window

- **401:** check the key in your private file, then Refresh detection.
- **403:** check API permissions, region/project restrictions and model access.
- **404:** Load models again, choose an available model and retry.
- **429:** check provider usage, API credits/quota and rate limits before retrying.
  App subscriptions do not necessarily include API credit.
- **Connection/timeout:** check the service and network, then retry the check.

A successful worker check is retained while you retry the cloud check. Changing
provider/model invalidates its cloud result; refreshing credentials invalidates
both. A cloud rejection never requires reinstalling Python, Docker or packages.
No paid cloud requests run at startup or during local installation. Connection
tests and task runs make real requests. The independent judge receives your task,
changed source and test evidence; choose a provider you permit to receive it.

The task tab includes a folder picker and task field. Choose a project outside
the AASS application. A successful connection check does not approve a task;
actual nonempty tests after the last write and independent review are required.

## Release checks and advanced use

A published release includes its exact Microsoft Defender scan report, SHA256SUMS,
dependency/source audits, SBOM and GitHub build attestation. Publication requires
Linux/Windows tests, an actual Windows GUI construction check, a clean runtime
installation and Defender scans of the ZIP and installed Python/browser payload.
A checksum proves integrity, not universal antivirus acceptance. Source remains
unsigned. If protection reports a threat, keep it enabled and inspect Protection
history; do not add exclusions or restore the withdrawn diagnostic patch.

The BAT entry points verify the release manifest in isolated Python mode before
application imports. A reviewed update retains local `.venv`, `.aass` and private
files; a changed dependency fingerprint triggers hash-verified wheel reinstall.
Use complete release files. Local `.env` files are Git-ignored and excluded from
release packaging. Keep them out of engineering target projects.

Advanced automation remains available through `Install-AASS.bat --help`,
`python install_aass.py`, `python local_app.py` (legacy terminal menu) and
`python -m orchestration_canvas`. Local stage logs/status are in `.aass`.
Only designated model-client subprocesses receive API keys. Package, daemon,
browser and worker-tool children have credentials stripped. Share specific
sanitized stage/status messages rather than environment dumps or private files.

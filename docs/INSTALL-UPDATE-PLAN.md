# Desktop installation and update plan

Implemented flow: download the complete GitHub ZIP, extract, double-click
Install-AASS.bat. The bootstrap checks the latest published verified release and
copies source into %LOCALAPPDATA%/Programs/AASS before building a runtime there.
GitHub Code ZIPs first fetch a complete verified release; raw main is never
labelled a scanned release. A newer unpublished source waits for publication.

The setup window reuses Docker/Ollama/models, installs hash-locked dependencies
and creates a custom AASS desktop shortcut after local checks pass. Cloud account
verification remains explicit and may incur API charges. Windows features and
restarts still need the computer owner. Python 3.12 including Tcl/Tk is required.

The app's Update button downloads the latest full published release from the fixed
MeetleJuice/AASS repository. Checks include checksum, clean source manifest,
matching Defender archive/runtime/browser evidence, dependency/source audit and
SBOM. Downloads are bounded; unsafe paths, links, binaries and private state are
rejected. There are no arbitrary update URLs or credentials in requests.

Before applying, the updater closes the GUI, takes exclusive locks, and saves the
current source and runtime. It updates managed source only, installs required
runtime changes, checks dependencies and the real Windows GUI/browser, refreshes
the icon, and restarts. Settings, credential-file paths and projects are preserved.
Failure restores both source and runtime. An interrupted transaction is recovered
by the desktop launcher using the complete verified backup engine before importing
potentially incomplete application modules. Only one GUI/update may own the app.

Source-only updates reuse hashed dependencies; changed dependency locks trigger
installation. Existing virtual environments are never relocated during installation.
Only the current rollback copy is retained after a successful update.

Verification covers model protocols, archive/evidence tampering, real filesystem
update/rollback, private settings preservation, locks, GUI cancellation/handoff,
Windows known Desktop/COM shortcut/icon, clean managed bootstrap and runtime
installation. Publication remains gated by Linux/Windows tests and Defender scans.

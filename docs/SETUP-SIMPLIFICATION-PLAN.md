# Guided setup implementation plan

## Problems observed

The Windows installation required PowerShell commands, folder navigation and
repeated terminal menus. Docker's WSL/Virtual Machine Platform prerequisite could
not be repaired by reinstalling AASS. Long downloads looked stalled. A withdrawn
diagnostic ZIP received an unidentified security warning. Credentials placed
beside the application were missed, and Notepad could append `.txt`. Local model
generation succeeded while the default Gemini judge model returned HTTP 404;
there was no way to choose an available model without writing API commands.

## Result to deliver

1. A double-click opens one graphical window, built with Python's standard Tk
   library. Local installation, cloud setup and running a project remain in that
   window. Existing CLI entry points remain usable for automation.
2. Local preparation streams stages and progress, reuses dependencies/models and
   has bounded timeouts/cancellation. Docker/WSL failures show a specific next
   action. A cloud error never forces a local reinstall.
3. Automatically recognize application `.env` and `.env.txt`, with a Browse
   button for any existing private credential file. Recognize UTF-8 and Notepad
   UTF-16 BOM text. Persist only the selected path and provider/model preference.
   Process environment bindings take precedence; never print/copy key contents.
4. Detect which providers have keys. List models from fixed official provider
   endpoints and choose an actual returned model ID. Catalog lookup makes no
   generation request and does not establish billing entitlement or access.
5. An explicitly labelled connection check tests the worker and cloud judge.
   Explain authentication, permission, missing model and quota failures in plain
   language. Retain a successful worker result while retrying only the cloud.
   Changing credentials/provider/model invalidates affected results. No silent
   provider switch or automatic paid requests.
6. Use a project folder picker and task field. Keep worker containment, token
   limits, independent review and secret filtering unchanged.
7. Package complete source, hash-pinned dependencies and a manifest. Verify
   Linux tests, real Windows installation, graphical construction and Microsoft
   Defender scans of both ZIP and installed payload before publishing a release.

## Acceptance checks

- Clean and repeated installation, spaces in paths, missing prerequisites and
  child cancellation do not leave a false ready state.
- Credential selection survives restart without saving values. `.env.txt` and
  UTF-16 load; symlinks, oversized/unreadable files and malformed selections fail
  visibly. Provider keys are never sent to another provider.
- Catalog pagination/filtering and HTTP failures are tested without real keys.
  Error output excludes provider response bodies and authentication headers.
- A model dropdown uses returned IDs; connection failure leaves setup usable.
- Windows CI constructs the actual GUI from the extracted release, closes it,
  installs the hash-locked runtime and scans the exact distributable/payload.
- Published assets have matching checksums, manifest, scan evidence and provenance.

## Machine/account boundaries

The application cannot enable firmware virtualization or reboot Windows on the
owner's behalf. It cannot create API billing entitlement or guarantee every
antivirus engine accepts unsigned source. Those cases need a clear next action,
not bypasses, repeated package installation or a misleading success indicator.

## Completion evidence

Implemented in source 9124d52 and published as AASS 1.2.0. Local integration tests,
actual Tk credential/catalog/404-retry flow, fresh extracted package installation,
Windows regressions/native GUI/browser installation and Defender ZIP/payload
scans passed. Downloaded public assets pass the matching evidence validator and
reproduce the local source archive byte-for-byte. See [validation](VALIDATION.md)
for the exact run, release and checksum. The remaining machine/account actions
are selecting an existing private file if needed and explicitly testing real
model access; setup makes no paid request before that action.

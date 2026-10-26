# Security and installation review — 1.1.0

## Incident scope
A user reported that their PC called the standalone diagnostic ZIP a virus.
The detection name/vendor was unavailable. The reported archive was removed from
current distribution. Neither a malware diagnosis nor a false-positive claim is
supported. Git history was preserved; old immutable URLs are historical artifacts,
not recommended downloads. No antivirus setting, Windows trust policy or TLS check
was disabled. No private files or credentials were uploaded to a scanning service.

## Confirmed findings and remediation

| Finding | Remediation |
| --- | --- |
| filelock 3.32.7 had three known advisories in pip-audit | Upgraded to 4.2.1, the reported fixed version; updated allowed dependency range and wheel hashes |
| Runtime install included developer/test/PostgreSQL tools | Separate runtime, development and security-tool locks |
| No local dependency hashes; implicit build downloads | Require hashed wheels only; pin build tools; disable isolated dependency fetching for the reviewed local project |
| One-off ZIP patches lacked consistent provenance/scan evidence | Withdraw patches; build one deterministic explicit-manifest release; release publication gated on Windows Defender and tests |
| Recursive Desktop search could read unrelated project .env files | Restrict discovery to Desktop .env and bounded named credential folders; explicit import remains available |
| Credential files accepted arbitrary AASS_ options | Recognized setting allowlist; cannot set executable paths or approve custom API hosts |
| API keys could follow an inconsistent provider/base URL | Validate HTTPS, provider adapter, official destination and explicit custom-host approval; reject conflicts |
| Installer/daemon subprocesses inherited API keys | Strip secret bindings by default; only designated model-client subprocesses receive them |
| HTTP errors hid service/status | Structured local/cloud stage, status, hostname and allowlisted provider error codes; no raw response bodies |
| Cloud rejection appeared as broken local installation | Distinct installed/configuration/live verification states; no reinstall for API quota/authentication issues |
| Host file writes could follow hardlinks; FIFO reads could hang | Atomic replacement; regular-file/size checks; reads and snapshots reject hardlinks |
| HTTP request routes did not cover browser WebSockets | Block WebSocket connections in scoped browser contexts |
| No release file/extra executable integrity check | Per-file manifest verification before batch setup/start; isolated stdlib verifier; unexpected runtime code rejected |

Known filelock advisories returned by the audit were CVE-2026-112940,
CVE-2026-112913 and CVE-2026-112907. These findings do not establish the cause of
the antivirus warning. The post-upgrade runtime dependency audit found no known
vulnerabilities at the time it ran; an advisory database cannot prove absence of
malware or unknown vulnerabilities.

## Research and trust contracts
- pip's [secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/)
  recommends `--require-hashes`, exact complete dependency pins, binary-only
  artifacts and `--no-deps` for local project installation. The official pip
  documentation source was read directly.
- GitHub's [artifact attestation concepts](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
  were read from the official github/docs source. Attestations bind an artifact
  to source/workflow identity; GitHub explicitly says they do not guarantee safety.
- The official microsoft/winget-cli README was consulted. Third-party prerequisite
  installation is now explicit; the user's already installed applications are reused.
- Microsoft's [Defender CLI reference](https://learn.microsoft.com/en-us/defender-endpoint/command-line-arguments-microsoft-defender-antivirus)
  and [SmartScreen overview](https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/)
  are relevant references. Direct access was blocked in this cloud network, so
  they are not represented as successfully read. The Windows job invokes the
  installed Microsoft-signed scanner and requires successful real results.
- Microsoft's [file submission portal](https://www.microsoft.com/en-us/wdsi/filesubmission)
  is the official route to request review of a suspected incorrect detection. No
  submission was made here; the original detection remains unknown.

## Release gate
Linux integrations and Windows tests must pass. Windows scans the exact ZIP and
its extracted payload using Microsoft Defender with recent signatures, verifies
the scanner's Microsoft signature, checks for detections/remediation and unchanged
archive bytes, and verifies the extracted manifest. Missing/stale/unavailable
Defender blocks publication. No scan result is inferred from a script's existence.

The publisher checks artifact checksums, source revision, successful matching scan,
dependency results and source security results before issuing GitHub provenance
and publishing source plus evidence. GitHub Actions references are pinned to
verified full commit IDs, with separate read-only test/scan jobs and a narrowly
permissioned publication job. No certificate or Authenticode signing identity is
available; releases clearly remain unsigned source.

Bandit reviews argument-array subprocess use as low-severity risk; all such calls
were reviewed for shell use, origin, bounds and trust. Narrow documented suppressions
cover validated loopback/HTTPS URL reads and Docker's container-only `/tmp` tmpfs;
these do not suppress arbitrary host temporary-file or URL findings.

## Limits
Defender's verdict is one engine's result for exact bytes/signatures/time, not a
promise about every antivirus product or SmartScreen reputation. A valid checksum
is not an antivirus verdict. Existing third-party installations, a compromised
Windows user account, malicious custom MCP server and host-kernel/browser exploits
remain outside the container guarantee. Keep application source and operator
configuration trusted; never use the AASS runtime as its own engineering target.

## Platform and process follow-up
The first strict Windows lock run exposed missing Windows-only requirements:
pywin32 (MCP), colorama (pytest) and tzdata (PostgreSQL). Exact reviewed versions
and wheel hashes were added with platform markers. Lock maintenance now validates
closure/specifiers/extras for Windows, Linux and macOS; the auditor neutralises
markers for advisory lookup so a Linux audit also checks Windows package versions.
All 37 runtime, 47 development and 33 audit-tool pins were checked without known
advisories. These counts include platform-specific packages, not all installed on
every platform.

Browser control and readiness now use a dedicated isolated stdio helper with
provider credentials stripped before the SDK/renderer starts. Docker/Git children
also receive filtered environments. A real browser regression verifies this
boundary and cleanup. New unversioned projects map safely even without Git.

The Windows release job additionally installs the exact clean end-user environment
and browser before scanning. Its Defender report records whether installed runtime
and browser bundles were included. Publication still waits for actual successful
scan and integrity evidence; this statement describes the gate, not a presumed result.

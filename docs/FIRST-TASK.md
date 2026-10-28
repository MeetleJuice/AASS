# Your first AASS task

Use a published release that has passed its Windows checks; see the dated
[release readiness](RELEASE-READINESS.md) record and the release's attached evidence.
This guide describes the existing desktop task interface, not a claim that your
PC has already passed installation. Version 1.2.1 uses the same task workflow
but starts from its extracted folder and has no desktop icon or Update button.

For 1.3.1 automatic setup, see [the consent and provider settings](AUTOMATIC-SETUP.md).
When automatic validation succeeds, the app opens the task tab directly. Use the
manual steps below only if setup reports a required action.

## Open and connect

1. For 1.3.x, open **AASS** from its desktop icon, or **Start-AASS.bat** in
   `%LOCALAPPDATA%\Programs\AASS`. For 1.2.1, open **Start-AASS.bat** in the
   extracted release folder; keep that folder in place after installation.
2. On **1. Setup**, use **Prepare / check this PC** if local preparation has not
   passed. Existing Python packages, Docker images and Ollama models are reused
   when their checks pass. Docker Desktop must have a running Linux engine.
3. Choose your existing private `.env` or `.env.txt` file if detection did not find
   it. Keep that file outside the project you give AASS.
4. Choose your cloud provider, click **Load models**, and select an available text
   model. Click **Test connections (uses API)**. This makes real requests and may
   incur charges. Both local Ollama generation and the independent judge must
   work for a task to finish with approval.

A cloud authentication, model or quota error needs a configuration/account fix;
it does not require reinstalling Docker, Ollama or Python packages. See
[connection recovery](WINDOWS-INSTALL.md#recover-from-connection-problems).

## Run a small project

1. Create a new folder named **AASS-first-task** on your Desktop. It must be
   separate from the extracted ZIP and the installed AASS folder.
2. Open **2. Run a task**, click **Browse...**, and choose that folder.
3. Paste this task:

   ```text
   Create text_utils.py with a slugify(text) function using only Python's
   standard library. Normalize Unicode with NFKD, discard characters that
   cannot be represented in ASCII, convert to lowercase, replace each run of
   characters other than a-z and 0-9 with one hyphen, and remove leading and
   trailing hyphens. Empty input or punctuation-only input returns an empty
   string. Do not modify unrelated files.

   Create test_text_utils.py using unittest. Cover these exact examples:
   "Hello, world!" -> "hello-world"
   "  many\tspaces\n" -> "many-spaces"
   "Café déjà vu" -> "cafe-deja-vu"
   "version_2.0" -> "version-2-0"
   "" -> ""
   "!!!" -> ""

   Run python -m unittest discover -v in the Docker sandbox. Inspect and repair
   any failing tests, rerun them after every code change, then request independent
   review. Do not install packages or use pytest.
   ```

4. Click **Run task (uses API)**. Leave the window open. The progress area shows
   subprocess messages and the final result; it is not a complete live transcript
   of every model action.
5. Wait for **Task passed tests and independent review.** A stopped or failed
   result is not approval. AASS requires nonzero tests after its last file write,
   followed by the independent cloud judge's approval.

The default sandbox supports standard-library `unittest`. It has no network and
does not install your project's dependencies. Tests see a read-only source copy;
they must put temporary output under the container's `/tmp` directory.

## Inspect and reopen

Open **AASS-first-task** in File Explorer. Inspect `text_utils.py` and
`test_text_utils.py` in your editor. In the same project's `.aass` folder:

- `canvas.json` records the final status, changed-file names and review or stop
  reason.
- `trajectory.json` records bounded action/failure metadata. It is not a full
  conversation or raw test-output archive.

Keep `.aass` private. If the task stops, source edits remain for inspection.
Correct the named service/configuration problem or submit a smaller repair task;
do not treat remaining files alone as proof of success.

Close AASS, reopen it using the version-appropriate launcher above, and choose
**AASS-first-task** again when you want another task. Files and history remain on
disk. The app does not automatically resume an interrupted run or restore the
previous task form.

## Other realistic tasks

These fit the current tools; each needs relevant `unittest` tests and cloud review:

1. Implement and test a small string utility such as the slug function above.
2. Fix an off-by-one bug in an existing Python function and add a regression test.
3. Convert CSV text to JSON with standard-library parsing and malformed-input tests.
4. Validate date strings with leap-year and invalid-date tests.
5. Refactor duplicated normalization code while preserving its tested behavior.

Browser and MCP access are advanced CLI capabilities requiring explicit operator
configuration. The desktop task form does not configure them. AASS does not
automatically commit, push or deploy the resulting project.

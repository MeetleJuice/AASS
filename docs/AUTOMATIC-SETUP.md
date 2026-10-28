# AASS 1.3.1 automatic setup and provider configuration

Download the official release, extract everything, put your private `.env.txt`
(or `.env`) beside `Install-AASS.bat`, and double-click that installer. It uses
its own directory, regardless of the terminal's current directory. Source is
installed permanently before the runtime is created. Existing Docker, Ollama,
installed models and matching locked dependencies are reused. The app opens and
creates its desktop shortcut after local checks pass.

For automatic cloud validation, add these non-secret settings to your private file:

```dotenv
AASS_SETUP_ALLOW_BILLABLE_CHECK=1
AASS_JUDGE_SERVICE=gemini
```

Replace `gemini` with your intended provider ID below. This is explicit consent
for up to **three generation/review requests to that provider** for a new
configuration. Requests may incur API charges. A failed or successful attempt is
remembered so reopening the app does not keep charging. Changing credentials
invalidates that receipt. Quota/authentication/server/network failures stop
fallback immediately; model/format 400/404 failures permit the bounded fallback.
Use Test connections to retry manually after resolving an account error.

Without the setting, installation and catalog discovery finish without billable
cloud generation; click **Test connections** once to consent. With multiple keys,
choose one provider or set `AASS_JUDGE_SERVICE`; AASS never fails over between
providers or treats a missing mandatory judge as ready. Working selections are
preserved. The successful result opens **Run a task** with **Ready to run tasks**.
Subsequent launches reuse the verification record and check local service
availability without another paid test. Each task still requires its own tests
and independent review; a setup receipt cannot approve a task.

## Supported model API routes

| Provider ID | Key binding | API format |
| --- | --- | --- |
| gemini | GEMINI_API_KEY or GOOGLE_API_KEY | Native generateContent |
| openai | OPENAI_API_KEY | Chat completions |
| anthropic | ANTHROPIC_API_KEY | Messages |
| groq | GROQ_API_KEY | Chat completions |
| openrouter | OPENROUTER_API_KEY | Chat completions |
| nvidia | NVIDIA_API_KEY | Chat completions |
| requesty | REQUESTY_API_KEY | Chat completions |
| huggingface | HUGGINGFACE_API_KEY or HF_TOKEN | Chat completions |
| cloudflare | CLOUDFLARE_API_TOKEN plus CLOUDFLARE_ACCOUNT_ID | Workers AI chat completions |
| custom | AASS_CUSTOM_API_KEY, or an explicitly named key binding | Configured supported format |

Catalogs return actual candidate IDs. A listed model is not proof of generation,
structured-output access, account credit or quota. A real judge request validates
compatibility before ready is reported. Providers can differ in supported
parameters. No automatic choice claims universal compatibility with every model.
An exact operator-selected model may be supplied as `AASS_NVIDIA_MODEL`,
`AASS_GROQ_MODEL`, etc. It still has to pass the real check.

For another AI model API, configure its endpoint and supported protocol explicitly:

```dotenv
AASS_JUDGE_SERVICE=custom
AASS_CUSTOM_BASE_URL=https://your-provider.example/v1
AASS_CUSTOM_PROTOCOL=openai
MY_VENDOR_API_KEY=your_private_value
AASS_CUSTOM_KEY_VARIABLE=MY_VENDOR_API_KEY
# Optional if catalog discovery is unavailable:
AASS_CUSTOM_MODEL=vendor/exact-model-id
```

Formats are `openai` chat completions, `anthropic` Messages, or native `gemini`
using Google's official host. A custom provider must implement the selected
protocol; an arbitrary unrelated REST API cannot act as a model judge. Custom
key names must end `_KEY` or `_TOKEN`. Alternatively use
`AASS_CUSTOM_API_KEY` directly. Catalogs default to `BASE_URL/models`;
`AASS_CUSTOM_MODELS_URL` can specify a different path on the **same HTTPS host**.
Credentials stay in headers; redirects and credentials embedded in URLs are
rejected. Cloudflare uses its account-scoped model catalog and text-generation
capability metadata. No unknown key is sent to a guessed endpoint.

## File priority and privacy

Process environment bindings take precedence. A file deliberately supplied beside
the new installer replaces the retained file reference, with `.env` before
`.env.txt`. Without a supplied file, the existing selected reference is retained.
A selected file prevents broader Desktop discovery. Legacy Desktop discovery
cannot introduce custom provider-routing configuration. Unknown settings are
ignored; only supported keys and explicitly declared custom bindings are loaded.
UTF-8, UTF-8 BOM and BOM-marked UTF-16 work, including quotes, blank lines and
inline comments. The original file is retained by absolute path; **keep it in
place**, or select its new location after moving it. Keys are never copied into
replaceable source, generated architecture, release archives or diagnostics.

Local models are not downloaded automatically. Install or select a compatible
model in Ollama if none is available. Only one worker model is selected. Missing
Python/system software, Docker virtualization or Windows restarts require owner
action. Existing Docker/Ollama services are safely started where supported.

**Export diagnostics** saves only version, readiness flags, selected provider and
sanitized failure metadata. It excludes credentials, private file paths, key
fingerprints and raw logs. Updates preserve private selection, provider/model
preferences and setup receipts. Keep antivirus, TLS and release verification on.

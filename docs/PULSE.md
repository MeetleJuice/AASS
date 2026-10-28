# AASS Pulse

Click **All Tests** to open the diagnostic laboratory and run its bounded default
suite. The default makes no generation requests: fixture model decisions drive
real Docker test execution, including seeded failures and independent acceptance
checks. Passing a negative control means Pulse detected bad code; it does not
mean the defective application passed. Results label fixture and live evidence.

Eight versioned benchmarks cover creation, repair, multiple artifacts, malformed
storage, schema recovery, alternating rewrites, interruption, and the expense
tracker CLI. The default normally takes about a minute once Docker is ready.
Missing services are blocked rather than converted to passes. Pulse writes only
its private `.aass/pulse/<run>` workspaces; it does not touch your task folder,
change settings, download models, or repair AASS itself.

Optional live local evaluation uses the already installed Ollama model. Optional
cloud review requires separate explicit consent each run and may incur API fees;
only generated benchmark source/tests are sent. The live suite shares the hard
64,000 reserved-token / 20-step ceiling across tasks and has per-task deadlines.
Tasks that cannot reach enabled independent review remain blocked. Unused or
unavailable actual usage/cost is never inferred from reserved allowances.

The timeline shows actual events and the progress count advances only on terminal
benchmark results. Cancel safely stops the owned benchmark process tree and
keeps partial records. A native Windows sound (where available) and completion
window offer Review Results. Raw source/model/test text is private and excluded
from export. Review lists the fixed report inventory; optional environment,
event and metric sections can be excluded before Create Diagnostic ZIP. The ZIP
is never uploaded. Open SUMMARY.md or the self-contained report.html to read it.
Comparisons require matching manifest, mode, model and environment fingerprints;
missing live identity makes a comparison unverified.

The supervisor now requires action-specific arguments in its Ollama schema,
retains actual latest failure feedback, and tests runnable changed snapshots
before further generation. It does not force testing after an arbitrary write
count. Independent benchmark acceptance files cannot be rewritten by the worker.
Repeated ineffective snapshots remain bounded by fixation and budget controls.
No test result or fixture verdict bypasses normal task review requirements.

Windows CI constructs the installed Pulse view and runs packaged diagnostics.
Windows Server CI is not physical Windows 10 or live RTX 3050 model acceptance.
Those destination checks must remain explicitly unverified until performed.

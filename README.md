# AASS
Autonomous Agent System Stack

# Autonomous Agent System Stack (AASS) vs. CRADLE 🚀

Welcome to the architectural codebase for **AASS 1.0 (Autonomous Agent System Stack)**, an asset blueprint built to establish an independent, self-correcting development software runtime engine on local consumer hardware.

## 🎯 The Ultimate Goal
To transcend standard, conversational AI models that experience memory limitations and loop stagnation, replacing them with a headless, un-babysat developer workspace. The stack utilizes local compute (`qwen3.5:9b` via Ollama) to process repeatable, zero-cost engineering tasks, and maps cloud keys via automated file intercept hooks to activate high-level cognitive supervision when barriers are hit.

---

## 🏛️ System Core Architectures & Jargon

### 🧠 1. Cognitive & Reasoning Layers
*   **Co-Regulation Design Agentic Loop (CRDAL):** The dual-loop framework based on Carnegie Mellon University research ("Supervising Ralph Wiggum"). A high-level supervisor agent monitors execution trajectories and injects overrides into a lower worker agent.
*   **Ralph Wiggum Loop (RWL):** A single-loop automated baseline. Spuns up an execution model freshly each turn to interact directly with system environments before discarding it to block context bloat.
*   **Design Fixation (Tunnel Vision):** The pathological loop state where an AI repeats localized, syntax-level modifications on a broken concept rather than stepping back to change strategies.

### 🔌 2. Integration & Infrastructure Layers
*   **Model Context Protocol (MCP):** An open standard protocol creating isolated, plug-and-play microservices for agents to query databases and file system arrays safely.
*   **Trajectory Summary (`trajectory.json`):** A dense, vectorized structural JSON timeline logging changes made and precise error signatures to manage memory without chat context bloat.
*   **Stall-Detection Intercept:** A deterministic circuit breaker that automatically monitors tracking logs and stops execution if an agent hits a fixation rut.

### 🛠️ 3. Environment & Verification Layers
*   **Computer Use (OSWorld Vision API):** Direct multi-modal vision-language automation allowing the engine to capture screenshots of a hidden browser, map coordinates, and click selectors to verify web interfaces.
*   **Asymmetric Evaluation (LLM-as-a-Judge):** An automated gatekeeper that passes code patches through an independent, premium model review process to analyze security, syntax, and style before delivery.
*   **Ephemeral Sandboxes:** Completely isolated, disposable local micro-VMs or container wrappers ensuring script crashes or hazardous code blocks are perfectly contained.

---

## 📊 How it Outperforms Commercial Apps (Ours vs. OpenAI Codex App)

| Feature Axis | OpenAI Codex (The App) | "Ours" (AASS Runtime) |
| :--- | :--- | :--- |
| **Interface Strategy** | Front-end app windows, visual note cards, and visual chat inputs. | **Headless Engine:** Streams raw command lines and dense data files. |
| **Context Longevity** | **Auto-Compaction:** Truncates older chats causing immediate instruction rot. | **State-Space Compaction:** Tracks history permanently via dense indices. |
| **Loop Resilience** | Freezes and demands manual user prompts when an error hits a wall. | **CRDAL Core Regulation:** Automatically shifts strategy via supervisor overrides. |
| **Compute Economy** | Tied to cloud pricing structures and rolling 5-hour quota windows. | **Hybrid Routing:** Free local Qwen 9B processing scaled by cloud APIs. |

---

## 🚀 Execution & Self-Evolution Pipeline

This system is configured to self-compile autonomously across a 5-layer checklist via the master prompt harness:
1. **Layer 1: Infrastructure & Safety** (Token Budget Caps, Sandboxing boundaries)
2. **Layer 2: Connectivity** (MCP Postgres and Git repo graph mappers)
3. **Layer 3: Worker Engine** (Local Ollama hooks, browser automation scripts)
4. **Layer 4: Quality Assurance** (LLM-as-a-Judge reviewer, trajectory logs)
5. **Layer 5: Executive Canvas** (CRDAL core supervisor orchestration graphs)



---

## AASS 1.0 runtime implementation

The five-layer headless Python runtime is implemented in this repository. The
architecture above describes the goal; actual verified capabilities and external
service requirements are documented separately below.

**Start locally:** install Python 3.12+, Docker and Ollama. Download/extract the
source, then double-click `Launch-AASS.cmd` on Windows or run
`bash launch-aass.sh` on Linux/macOS. The launcher installs locked Python
dependencies and detects Desktop `.env` files, recognized cloud keys, and your
actual local Ollama models. It prefers `qwen3.5:9b` when installed. It never
writes credential values into the architecture JSON or repository.

```sh
python launch_aass.py doctor
python launch_aass.py verify-live
python launch_aass.py run --workspace /absolute/path/to/project \
  --task "Implement the requested feature and verify it with unit tests"
```

Use a separate target project, so generated changes cannot rewrite the executing
AASS runtime. Worker tests execute in bounded, networkless Docker containers.
The independent cloud judge must approve before a task can report success.
Unavailable model services and missing credentials fail readiness explicitly.
This is a bounded Python engineering runtime, not an unrestricted OS agent or a
proof that arbitrary generated programs are production safe.

- [Implementation plan](docs/PLAN.md)
- [Local setup, credentials, MCP, browser and deployment](docs/OPERATIONS.md)
- [Architecture and trust boundaries](docs/ARCHITECTURE.md)
- [Validation evidence](docs/VALIDATION.md)

The original supplied initializer was corrected to preserve telemetry, report
actual Ollama availability, and keep secret values out of generated specifications.
Browser automation uses Playwright with optional screenshot input to the local
vision worker; it does not bundle an OSWorld service.

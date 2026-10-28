"""Metadata-only export by construction. Arbitrary files/text are never archived."""

import html
import json
import re
import zipfile
from pathlib import Path

from pulse.benchmarks import manifest
from pulse.events import metadata, read_events

STATUS = {"passed", "failed", "skipped", "blocked", "cancelled", "timed_out", "running"}
EVIDENCE = {"negative_control_detected", "fixture_harness", "interruption_retained", "live"}
ERRORS = {
    "docker_cleanup_failed",
    "budget_exhausted",
    "review_not_enabled",
    "task_incomplete",
    "worker_unavailable",
    "tool_unavailable",
    "assertion_failed",
    "execution_error",
    "cancelled",
    "deadline_exceeded",
    "process_failed",
    "suite_budget_exhausted",
    "docker_unavailable",
    "invalid_result",
}
EVENTS = {
    "cleanup_failed",
    "action_started",
    "action_returned",
    "suite_started",
    "suite_finished",
    "suite_error",
    "test_started",
    "test_finished",
    "model_requested",
    "model_returned",
    "action_rejected",
    "schema_recovered",
    "corrective_feedback",
    "file_written",
    "first_test",
    "tool_started",
    "tool_finished",
    "verification_checkpoint",
    "review_budget_checkpoint",
    "review_requested",
    "review_returned",
    "task_finished",
    "strategy_pivot",
}
COMPONENTS = {"suite", "worker", "supervisor", "acceptance", "judge"}
ACTIONS = {"read", "write", "map", "test", "browser", "mcp", "finish", "model", "unknown"}
FIELDS = {"path", "content", "command", "reason", "operation", "tool", "arguments", "invalid"}
IDS = {case["id"] for case in manifest()["cases"]}


def load(directory, name):
    path = Path(directory) / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 3 * 1024 * 1024:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def number(value):
    return value if type(value) in (int, float) and 0 <= value <= 10**12 else None


def safe_summary(raw):
    raw = raw if isinstance(raw, dict) else {}
    result = {
        key: number(raw.get(key))
        for key in [
            "schema",
            "completed",
            "total",
            "duration",
            "reserved_tokens",
            "remaining_tokens",
        ]
    }
    result.update(
        status=raw.get("status") if raw.get("status") in STATUS else "blocked",
        mode=raw.get("mode") if raw.get("mode") in {"live", "deterministic"} else "unknown",
        cloud_consent=raw.get("cloud_consent") is True,
        counts={s: number(raw.get("counts", {}).get(s, 0)) for s in STATUS if s != "running"},
        actual_cost="unavailable",
        events_truncated=raw.get("events_truncated") is True,
    )
    for key, pattern in [
        ("run_id", r"[0-9a-f]{32}"),
        ("manifest_hash", r"[0-9a-f]{64}"),
        ("benchmark_version", r"\d+\.\d+\.\d+"),
    ]:
        v = raw.get(key)
        result[key] = v if isinstance(v, str) and re.fullmatch(pattern, v) else None
    return result


def safe_environment(raw):
    raw = raw if isinstance(raw, dict) else {}
    from provider_registry import providers

    result = {}
    for key in ["aass_version", "python", "ollama_version"]:
        value = raw.get(key)
        result[key] = (
            value
            if isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+", value)
            else "unavailable"
        )
    result["system"] = (
        raw.get("system") if raw.get("system") in {"Windows", "Linux", "Darwin"} else "unavailable"
    )
    result["architecture"] = (
        raw.get("architecture")
        if raw.get("architecture") in {"AMD64", "x86_64", "arm64", "aarch64", "x86"}
        else "unavailable"
    )
    for key in [
        "docker_command",
        "ollama_command",
        "docker_ready",
        "worker_ready",
        "sandbox_ready",
    ]:
        result[key] = raw.get(key) is True
    for key in ["browser", "dependencies", "installation_integrity"]:
        value = raw.get(key)
        result[key] = (
            value
            if value
            in {
                "ready",
                "unavailable",
                "unverified",
                "consistent",
                "inconsistent",
                "verified",
                "failed",
            }
            else "unavailable"
        )
    result["provider"] = (
        raw.get("provider") if raw.get("provider") in providers() else "unavailable"
    )
    result["configured_providers"] = [
        v for v in raw.get("configured_providers", []) if v in providers()
    ]
    for key in ["worker_model_hash", "judge_model_hash", "commit"]:
        v = raw.get(key)
        result[key] = v if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{40,64}", v) else None
    result.update(cpu_count=number(raw.get("cpu_count")), ram="unavailable", gpu="unavailable")
    return result


def safe_results(raw):
    result = []
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        if row.get("id") not in IDS:
            continue
        item = {
            "id": row["id"],
            "status": row.get("status") if row.get("status") in STATUS else "failed",
            "mode": "live" if row.get("mode") == "live" else "deterministic",
        }
        for key in ["agent_completed", "acceptance_passed", "real_tools"]:
            item[key] = row.get(key) is True
        for key in ["duration", "reserved_tokens", "iterations"]:
            item[key] = number(row.get(key))
        item["evidence"] = row.get("evidence") if row.get("evidence") in EVIDENCE else "unavailable"
        item["review"] = (
            row.get("review")
            if row.get("review") in {"fixture", "live", "not_enabled", "not_requested"}
            else "unavailable"
        )
        if row.get("error_category") in ERRORS:
            item["error_category"] = row["error_category"]
        result.append(item)
    return result


def safe_events(raw):
    rows = []
    allowed = {
        "component": COMPONENTS,
        "event_type": EVENTS,
        "test_id": IDS,
        "action": ACTIONS,
        "action_type": ACTIONS,
        "field": FIELDS,
        "mode": {"live", "deterministic"},
        "schema_version": {"v2"},
        "outcome": STATUS | {"approved", "rejected", "stopped"},
        "error_category": ERRORS
        | {
            "worker_action_schema",
            "worker_json_invalid",
            "worker_output_truncated",
            "budget_exhausted",
            "safety_stop",
            "suite_busy",
            "engine_error",
        },
    }
    for event in raw:
        row = metadata(event)
        for key, values in allowed.items():
            if key in row and row[key] not in values:
                del row[key]
        for key in ["event_id"]:
            if isinstance(event.get(key), str) and re.fullmatch(r"[0-9a-f]{24}", event[key]):
                row[key] = event[key]
        if isinstance(event.get("timestamp"), str) and re.fullmatch(
            r"[0-9T:.+Z-]{20,40}", event["timestamp"]
        ):
            row["timestamp"] = event["timestamp"]
        row.pop("provider", None)  # Available registered providers are in environment.
        for key in ["elapsed", "sequence"]:
            row[key] = number(event.get(key))
        rows.append(row)
    return rows


def documents(directory, *, include_environment=True, include_events=True, include_metrics=True):
    directory = Path(directory)
    summary = safe_summary(load(directory, "summary.json"))
    results = safe_results(load(directory, "benchmark-results.json"))
    events = safe_events(read_events(directory / "events.jsonl")) if include_events else []
    env = (
        safe_environment(load(directory, "environment.json"))
        if include_environment
        else {"excluded": True}
    )
    model = (
        [e for e in events if e.get("component") in {"worker", "judge"}] if include_metrics else []
    )
    tools = (
        [
            e
            for e in events
            if e.get("event_type") in {"tool_started", "tool_finished", "first_test"}
        ]
        if include_metrics
        else []
    )
    failures = [r for r in results if r["status"] in {"failed", "blocked", "timed_out"}]
    recovery = [
        e
        for e in events
        if e.get("event_type")
        in {"schema_recovered", "corrective_feedback", "strategy_pivot", "verification_checkpoint"}
    ]
    lines = [
        "# AASS Pulse results",
        "",
        f"Overall: {summary['status']}. Completed {summary['completed']}/{summary['total']}.",
        f"Mode: {summary['mode']}. Fixture success is not live AI acceptance.",
        "Reserved tokens are conservative allowances, not actual billed usage. Cost: unavailable.",
        "",
        "| Benchmark | Outcome | Evidence | Independent acceptance | Review |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r['id']} | {r['status']} | {r['evidence']} | {r['acceptance_passed']} | {r['review']} |"
        )
    hints = {
        "docker_unavailable": "Open Docker Desktop with its Linux engine and complete local sandbox preparation.",
        "worker_unavailable": "Start Ollama and select an already installed worker model; Pulse never downloads models.",
        "deadline_exceeded": "The benchmark exceeded its versioned deadline; inspect retained partial events.",
        "budget_exhausted": "Inspect schema retries, rewrites and time to first test before changing workload scope.",
        "suite_budget_exhausted": "The shared live-suite ceiling was reached; this task was not attempted.",
        "review_not_enabled": "Acceptance passed but live independent review was not enabled; approval remains blocked.",
        "task_incomplete": "The task did not reach acceptance plus independent approval; inspect test/recovery events.",
    }
    if failures:
        lines += ["", "Failure explanations:"]
        for row in failures:
            category = row.get("error_category", "execution_error")
            lines.append(
                f"- {row['id']}: {category}. "
                + hints.get(
                    category,
                    "Inspect the linked benchmark and its event timeline; no raw exception text is exported.",
                )
            )
    lines += [
        "",
        "Measurements:",
        f"- Model requests: {sum(e.get('request_count', 0) for e in model)}; generation duration reported: {sum(e.get('duration', 0) for e in model):.3f}s.",
        f"- Tool execution duration reported: {sum(e.get('duration', 0) for e in tools if e.get('event_type') == 'tool_finished'):.3f}s.",
        "- First-test timing and budget appear in first_test events. Missing provider counts remain unavailable.",
        "- Task adherence is measured by fixed acceptance assertions; AASS has no explicit planning subsystem.",
    ]
    text = "\n".join(lines) + "\n"
    references = ", ".join(r["id"] for r in failures[:3]) or "no failing benchmarks in this run"
    recovery_refs = (
        ", ".join(e.get("event_id", "unavailable") for e in recovery[:3])
        or "no recorded interventions"
    )
    recommendations = (
        "1. Resolve blocked/failed benchmark evidence first: " + references + ".\n"
        "2. Review interventions before adjusting budgets: event IDs " + recovery_refs + ".\n"
        "3. Establish or repeat a consented live worker/review baseline using the same manifest and environment; fixtures cannot establish model capability.\n"
    )
    entries = {
        "README.txt": "AASS Pulse schema 1. Open SUMMARY.md or report.html. No automatic upload.\n"
        "Deterministic runs test the harness using fixture decisions and real tools.\n"
        "Negative controls PASS when independent checks reject a defective app.\n"
        "Source, raw model/test output, paths, private files and exception text are excluded.\n",
        "SUMMARY.md": text,
        "summary.json": summary,
        "environment.json": env,
        "benchmark-results.json": results,
        "events.jsonl": "".join(json.dumps(e) + "\n" for e in events),
        "model-metrics.json": {
            "events": model,
            "actual_cost": "unavailable",
            "usage": "reported counts only; missing counts unavailable",
        },
        "tool-metrics.json": tools,
        "failures.json": failures,
        "recovery.json": recovery,
        "verification.json": [
            {
                "id": r["id"],
                "acceptance_passed": r["acceptance_passed"],
                "review": r["review"],
                "agent_completed": r["agent_completed"],
            }
            for r in results
        ],
        "recommendations.md": recommendations,
        "report.html": '<!doctype html><meta charset="utf-8"><title>AASS Pulse</title><style>body{font:16px system-ui;max-width:1000px;margin:3em auto}pre{white-space:pre-wrap}</style><h1>AASS Pulse</h1><pre>'
        + html.escape(text)
        + "</pre>",
    }
    encoded = {
        k: (v if isinstance(v, str) else json.dumps(v, indent=2)) for k, v in entries.items()
    }
    import hashlib

    artifacts = []
    approved = {
        "sample.py",
        "test_sample.py",
        "README.md",
        "expense_tracker.py",
        "test_expense_tracker.py",
        "test_acceptance.py",
        "unrelated.txt",
        "notes.py",
    }
    from settings import is_link

    for case in manifest()["cases"]:
        workspace = directory / case["id"] / "workspace"
        if is_link(directory / case["id"]) or is_link(workspace):
            continue
        for name in sorted(approved):
            path = workspace / name
            if (
                not is_link(path)
                and path.is_file()
                and path.stat().st_nlink == 1
                and path.stat().st_size <= 65536
            ):
                artifacts.append(
                    {
                        "test_id": case["id"],
                        "name": name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "included": False,
                    }
                )
    inventory = {
        "benchmark_artifacts": artifacts,
        "included": [
            {"name": k, "bytes": len(v.encode()), "sha256": hashlib.sha256(v.encode()).hexdigest()}
            for k, v in encoded.items()
        ],
        "excluded": [
            "private files",
            "user projects",
            "generated source",
            "raw model responses",
            "raw test outputs",
            "exception messages",
            "absolute paths",
        ],
        "optional": {
            "environment": include_environment,
            "events": include_events,
            "metrics": include_metrics,
        },
        "truncated": summary.get("events_truncated", False),
        "unavailable": ["actual monetary cost", "unsupported CPU/RAM/GPU sampling"],
        "source_or_model_text_included": False,
    }
    encoded["artifacts-manifest.json"] = json.dumps(inventory, indent=2)
    return encoded


def export_zip(directory, destination, **options):
    # Build exclusively from fixed filenames and projected fields; no glob/archive
    # of a workspace or user-selected arbitrary source file is possible.
    content = documents(directory, **options)
    if Path(destination).suffix.lower() != ".zip":
        raise ValueError("Choose a ZIP filename")
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in content.items():
            archive.writestr(name, text.encode("utf-8"))
    return list(content)


def open_report(path):
    with zipfile.ZipFile(path) as archive:
        if (
            len(archive.infolist()) > 20
            or sum(i.file_size for i in archive.infolist()) > 5 * 1024 * 1024
        ):
            raise ValueError("Report exceeds limits")
        if any(
            "/" in i.filename or "\\" in i.filename or i.filename.startswith(".")
            for i in archive.infolist()
        ):
            raise ValueError("Unsafe report path")
        return {
            "summary": safe_summary(json.loads(archive.read("summary.json"))),
            "environment": safe_environment(json.loads(archive.read("environment.json"))),
        }

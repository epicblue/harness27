#!/usr/bin/env python3
"""Compare two benchmark reports while exporting metrics only.

This module deliberately uses an allowlist: raw prompts, model replies, reasoning,
tool arguments/results, verifier output and unknown fields are never copied into the
comparison artifact.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

SCHEMA_VERSION = 1
MAX_REPORT_BYTES = 64 * 1024 * 1024
CASE_NAME = re.compile(r"case_[a-z0-9_]+\Z")
RUN_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
VALID_STATUSES = {"passed", "failed", "error", "skipped"}
CONFIG_KEYS = (
    "python_version",
    "model",
    "base_url",
    "temperature",
    "max_tokens",
    "timeout_seconds",
    "max_steps",
    "max_context_chars",
    "repeat",
    "shell_opt_in",
    "keep_workspaces",
)


def _nonnegative_int(value, label):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _nonnegative_number(value, label):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite nonnegative number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite nonnegative number") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be a finite nonnegative number")
    return number


def _normalize_report(report, label):
    if not isinstance(report, dict):
        raise ValueError(f"{label} must be a JSON object")
    schema_version = report.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) \
            or schema_version != SCHEMA_VERSION:
        raise ValueError(f"{label} has an unsupported schema_version")

    run_id = report.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ValueError(f"{label} has an invalid run_id")

    harness_fingerprint = report.get("harness_fingerprint_sha256")
    if harness_fingerprint is not None and (
            not isinstance(harness_fingerprint, str) or not SHA256.fullmatch(harness_fingerprint)):
        raise ValueError(f"{label} has an invalid harness fingerprint")

    config = report.get("config", {})
    if not isinstance(config, dict):
        raise ValueError(f"{label} config must be a JSON object")
    safe_config = {key: config[key] for key in CONFIG_KEYS if key in config}

    rows = report.get("results")
    if not isinstance(rows, list):
        raise ValueError(f"{label} results must be a JSON array")
    by_case = {}
    seen_trials = set()
    for index, row in enumerate(rows):
        row_label = f"{label} result {index + 1}"
        if not isinstance(row, dict):
            raise ValueError(f"{row_label} must be a JSON object")
        case_name = row.get("case")
        if not isinstance(case_name, str) or not CASE_NAME.fullmatch(case_name):
            raise ValueError(f"{row_label} has an invalid case name")
        fingerprint = row.get("fingerprint_sha256")
        if not isinstance(fingerprint, str) or not SHA256.fullmatch(fingerprint):
            raise ValueError(f"{row_label} has an invalid case fingerprint")
        status = row.get("status")
        if not isinstance(status, str) or status not in VALID_STATUSES:
            raise ValueError(f"{row_label} has an invalid status")
        trial = row.get("trial")
        if not isinstance(trial, int) or isinstance(trial, bool) or trial < 1:
            raise ValueError(f"{row_label} has an invalid trial number")
        trial_key = (case_name, trial)
        if trial_key in seen_trials:
            raise ValueError(f"{label} contains a duplicate case/trial pair")
        seen_trials.add(trial_key)

        safe_row = {
            "status": status,
            "completed": row.get("agent_status") == "completed",
            "steps_used": _nonnegative_int(row.get("steps_used"), f"{row_label} steps_used"),
            "elapsed_seconds": _nonnegative_number(
                row.get("elapsed_seconds"), f"{row_label} elapsed_seconds"),
            "tool_errors": _nonnegative_int(row.get("tool_errors"), f"{row_label} tool_errors"),
        }
        case_group = by_case.setdefault(case_name, {"fingerprints": set(), "rows": []})
        case_group["fingerprints"].add(fingerprint)
        case_group["rows"].append(safe_row)

    return {
        "run_id": run_id,
        "harness_fingerprint": harness_fingerprint,
        "config": safe_config,
        "by_case": by_case,
    }


def read_report(path):
    """Read a runner report without retaining or forwarding unknown content."""
    path = Path(path)
    try:
        if not path.is_file():
            raise ValueError("report must be a regular file")
        size = path.stat().st_size
        if size > MAX_REPORT_BYTES:
            raise ValueError("report exceeds the supported size limit")
        raw = path.read_bytes()
        report = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"could not read a valid JSON report: {type(exc).__name__}") from exc
    return _normalize_report(report, path.name)


def _metrics(rows):
    passed = sum(row["status"] == "passed" for row in rows)
    failed = sum(row["status"] == "failed" for row in rows)
    skipped = sum(row["status"] == "skipped" for row in rows)
    errors = sum(row["status"] == "error" for row in rows)
    attempts = passed + failed
    executed_rows = [row for row in rows if row["status"] != "skipped"]
    executed = len(executed_rows)
    completed = sum(row["completed"] for row in executed_rows)

    def mean(key):
        return round(sum(row[key] for row in executed_rows) / executed, 3) if executed else None

    return {
        "executed": executed,
        "attempts": attempts,
        "verified_passes": passed,
        "verified_failures": failed,
        "success_rate": round(passed / attempts, 4) if attempts else None,
        "agent_completed": completed,
        "completion_rate": round(completed / executed, 4) if executed else None,
        "errors": errors,
        "skipped": skipped,
        "tool_errors": sum(row["tool_errors"] for row in executed_rows),
        "mean_steps": mean("steps_used"),
        "mean_elapsed_seconds": mean("elapsed_seconds"),
    }


def _percentage_point_delta(before, after, key):
    before_rate = before[key]
    after_rate = after[key]
    if before_rate is None or after_rate is None:
        return None
    return round((after_rate - before_rate) * 100, 2)


def _delta(before, after):
    return {
        "verified_passes": (
            after["verified_passes"] - before["verified_passes"]
            if before["attempts"] or after["attempts"] else None
        ),
        "success_rate_percentage_points": _percentage_point_delta(
            before, after, "success_rate"),
        "completion_rate_percentage_points": _percentage_point_delta(
            before, after, "completion_rate"),
        "mean_elapsed_seconds": (
            round(after["mean_elapsed_seconds"] - before["mean_elapsed_seconds"], 3)
            if before["mean_elapsed_seconds"] is not None
            and after["mean_elapsed_seconds"] is not None else None
        ),
    }


def _compare_normalized_reports(baseline, candidate):
    if baseline["harness_fingerprint"] is None or candidate["harness_fingerprint"] is None:
        harness_unchanged = None
    else:
        harness_unchanged = baseline["harness_fingerprint"] == candidate["harness_fingerprint"]

    changed_config_keys = []
    for key in CONFIG_KEYS:
        before_has_key = key in baseline["config"]
        after_has_key = key in candidate["config"]
        if before_has_key != after_has_key or (
                before_has_key and baseline["config"][key] != candidate["config"][key]):
            changed_config_keys.append(key)

    baseline_names = set(baseline["by_case"])
    candidate_names = set(candidate["by_case"])
    common_names = baseline_names & candidate_names
    baseline_only = sorted(baseline_names - candidate_names)
    candidate_only = sorted(candidate_names - baseline_names)
    changed_definitions = []
    case_comparisons = []
    comparable_baseline_rows = []
    comparable_candidate_rows = []

    for case_name in sorted(baseline_names | candidate_names):
        before_group = baseline["by_case"].get(case_name)
        after_group = candidate["by_case"].get(case_name)
        if before_group is None or after_group is None:
            definition_unchanged = None
            comparable = False
        else:
            before_consistent = len(before_group["fingerprints"]) == 1
            after_consistent = len(after_group["fingerprints"]) == 1
            definition_unchanged = (
                before_consistent and after_consistent
                and before_group["fingerprints"] == after_group["fingerprints"]
            )
            if not definition_unchanged:
                changed_definitions.append(case_name)
            comparable = definition_unchanged and harness_unchanged is True

        before_metrics = _metrics(before_group["rows"]) if before_group else None
        after_metrics = _metrics(after_group["rows"]) if after_group else None
        case_delta = _delta(before_metrics, after_metrics) if comparable else {
            "verified_passes": None,
            "success_rate_percentage_points": None,
            "completion_rate_percentage_points": None,
            "mean_elapsed_seconds": None,
        }
        case_comparisons.append({
            "case": case_name,
            "case_definition_unchanged": definition_unchanged,
            "comparable": comparable,
            "baseline": before_metrics,
            "candidate": after_metrics,
            "delta": case_delta,
        })
        if comparable:
            comparable_baseline_rows.extend(before_group["rows"])
            comparable_candidate_rows.extend(after_group["rows"])

    baseline_summary = _metrics(comparable_baseline_rows)
    candidate_summary = _metrics(comparable_candidate_rows)
    warnings = [
        "Comparison is descriptive only; it does not establish statistical significance or general model capability.",
        "The export includes allowlisted metrics only; it omits prompts, answers, reasoning, tool content, verifier text and configuration values.",
    ]
    if harness_unchanged is False:
        warnings.append("Harness fingerprints differ; no case-level deltas are marked comparable.")
    elif harness_unchanged is None:
        warnings.append("A harness fingerprint is missing; no case-level deltas are marked comparable.")
    if changed_config_keys:
        warnings.append("Evaluation configuration differs in: " + ", ".join(changed_config_keys) + ".")
    if baseline_only or candidate_only:
        warnings.append("Only cases present in both reports are considered for matched comparisons.")
    if changed_definitions:
        warnings.append("Changed or internally inconsistent case definitions are excluded from deltas.")
    if not any(row["comparable"] for row in case_comparisons):
        warnings.append("No cases have both an unchanged case definition and an unchanged harness fingerprint.")

    return {
        "comparison_schema_version": 1,
        "baseline_run_id": baseline["run_id"],
        "candidate_run_id": candidate["run_id"],
        "compatibility": {
            "harness_unchanged": harness_unchanged,
            "changed_config_keys": changed_config_keys,
            "common_case_count": len(common_names),
            "baseline_only_cases": baseline_only,
            "candidate_only_cases": candidate_only,
            "changed_case_definitions": changed_definitions,
            "comparable_case_count": sum(row["comparable"] for row in case_comparisons),
        },
        "case_comparisons": case_comparisons,
        "matched_summary": {
            "baseline": baseline_summary,
            "candidate": candidate_summary,
            "delta": _delta(baseline_summary, candidate_summary),
        },
        "warnings": warnings,
    }


def compare_reports(baseline_report, candidate_report):
    """Return an allowlisted, content-free comparison of two runner reports."""
    baseline = _normalize_report(baseline_report, "baseline report")
    candidate = _normalize_report(candidate_report, "candidate report")
    return _compare_normalized_reports(baseline, candidate)


def _write_private_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parser():
    result = argparse.ArgumentParser(
        description="Compare two benchmark reports and export allowlisted metrics only.")
    result.add_argument("--baseline", required=True, help="baseline runner JSON report")
    result.add_argument("--candidate", required=True, help="candidate runner JSON report")
    result.add_argument("--output", default="-", help="output JSON path; default: stdout")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        baseline_path = Path(args.baseline)
        candidate_path = Path(args.candidate)
        report = _compare_normalized_reports(
            read_report(baseline_path), read_report(candidate_path))
        if args.output == "-":
            json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        else:
            output_path = Path(args.output)
            resolved_output = output_path.resolve()
            if resolved_output in {baseline_path.resolve(), candidate_path.resolve()}:
                raise ValueError("output path must not replace either input report")
            _write_private_report(output_path, report)
    except (OSError, ValueError) as exc:
        print(f"benchmark comparison failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

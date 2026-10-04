"""Local, content-redacted analysis of Harness27 CLI run traces."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import tempfile
import uuid

DEFAULT_RUNS_DIR = Path(".harness27/runs")
DEFAULT_REPORT_DIR = Path(".harness27/analytics")
LABEL_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")
SESSION_RE = re.compile(r"(?:[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}|run-[0-9a-f]{16})")
ERROR_TYPE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,63}")
STATUSES = {"completed", "step_limit", "context_limit", "length_truncated", "error"}
TOOL_NAMES = {"list_files", "read_file", "write_file", "shell"}
LABEL_FIELDS = ("task_id", "task_category", "config_id")
TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")
QUESTION_FIELDS = (
    "q1_start_clarity",
    "q2_progress_visibility",
    "q3_approval_control",
    "q4_result_checkability",
    "q5_effort_time",
    "q6_troubleshooting",
    "q7_reuse",
)
FRICTION_CODES = {
    "setup", "tool_call", "file_ops", "approval", "latency_timeout", "budget",
    "docs", "result_validation", "safety_privacy", "none", "other",
}
TASK_OUTCOMES = {"completed", "partial", "failed", "aborted", "infrastructure_error"}
VERIFICATION_RESULTS = {"passed", "failed", "not_available", "pending"}
DENIAL_MESSAGES = {"用户拒绝写入", "用户拒绝执行命令"}
MAX_TIMELINE_EVENTS = 2_000


def _nonnegative_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _nonnegative_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _round_or_none(value):
    return None if value is None else round(value, 3)


def _label(value):
    return value if isinstance(value, str) and LABEL_RE.fullmatch(value) else None


def _timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        result = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _timestamp_text(value):
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def _session_id(path):
    stem = path.stem
    if SESSION_RE.fullmatch(stem):
        return stem
    # Avoid exporting arbitrary filenames (which could contain personal data).
    return "run-" + hashlib.sha256(stem.encode("utf-8", errors="replace")).hexdigest()[:16]


def _empty_session(session_id):
    return {
        "session_id": session_id,
        "start_time_utc": None,
        "end_time_utc": None,
        "duration_seconds": None,
        "status": "incomplete",
        "agent_steps": 0,
        "assistant_seconds": 0.0,
        "tool_seconds": None,
        "timed_tool_calls": 0,
        "tool_calls": 0,
        "tool_successes": 0,
        "tool_errors": 0,
        "tool_denials": 0,
        "approval_requests": 0,
        "approval_approvals": 0,
        "approval_denials": 0,
        "approval_data_complete": True,
        "tool_counts": {},
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "usage_events": 0,
        "task_id": None,
        "task_category": None,
        "config_id": None,
        "task_outcome": None,
        "independent_verification": None,
        "error_type": None,
        "trace_issue_count": 0,
        "timeline_truncated": False,
        "timeline": [],
    }


def _push_timeline(session, event):
    if len(session["timeline"]) < MAX_TIMELINE_EVENTS:
        session["timeline"].append(event)
    else:
        session["timeline_truncated"] = True


def analyze_trace(path):
    """Read one JSONL trace and return only allowlisted, content-free fields."""
    path = Path(path)
    session = _empty_session(_session_id(path))
    tool_counts = Counter()
    token_sums = Counter()
    token_observations = Counter()
    assistant_steps = 0
    assistant_seconds = 0.0
    tool_seconds = 0.0
    timed_tool_calls = 0
    first_time = None
    last_time = None
    finish_time = None

    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                session["trace_issue_count"] += 1
                continue
            if not isinstance(record, dict) or not isinstance(record.get("event"), str):
                session["trace_issue_count"] += 1
                continue
            event_name = record["event"]
            data = {key: value for key, value in record.items()
                    if key not in {"event", "time", "trace_schema_version"}}
            event_time = _timestamp(record.get("time"))
            if event_time is not None:
                if first_time is None:
                    first_time = event_time
                last_time = event_time
            if not isinstance(data, dict):
                session["trace_issue_count"] += 1
                continue

            if event_name == "start":
                session["start_time_utc"] = _timestamp_text(event_time)
                for field in LABEL_FIELDS:
                    session[field] = _label(data.get(field)) or session[field]
                _push_timeline(session, {
                    "event": "start",
                    "task_id": session["task_id"],
                    "task_category": session["task_category"],
                    "config_id": session["config_id"],
                })
            elif event_name == "assistant":
                assistant_steps += 1
                seconds = _nonnegative_number(data.get("seconds"))
                if seconds is not None:
                    assistant_seconds += seconds
                message = data.get("message")
                calls = message.get("tool_calls") if isinstance(message, dict) else None
                call_count = len(calls) if isinstance(calls, list) else 0
                step = _nonnegative_int(data.get("step"))
                timeline_item = {"event": "assistant", "step": step,
                                 "tool_call_count": call_count,
                                 "seconds": _round_or_none(seconds)}
                reason = data.get("finish_reason")
                if isinstance(reason, str) and reason in {
                        "stop", "length", "tool_calls", "function_call", "content_filter", "unknown"}:
                    timeline_item["finish_reason"] = reason
                _push_timeline(session, timeline_item)
                usage = data.get("usage")
                if isinstance(usage, dict):
                    session["usage_events"] += 1
                    for field in TOKEN_FIELDS:
                        amount = _nonnegative_int(usage.get(field))
                        if amount is not None:
                            token_sums[field] += amount
                            token_observations[field] += 1
            elif event_name == "tool":
                session["tool_calls"] += 1
                raw_name = data.get("name")
                name = raw_name if isinstance(raw_name, str) and raw_name in TOOL_NAMES else "other"
                tool_counts[name] += 1
                result = data.get("result")
                result = result if isinstance(result, dict) else {}
                ok = result.get("ok") if isinstance(result.get("ok"), bool) else None
                error_label = result.get("error")
                approval = result.get("approval")
                legacy_denial = isinstance(error_label, str) and error_label in DENIAL_MESSAGES
                denied = (approval == "denied" or legacy_denial)
                if ok is True:
                    session["tool_successes"] += 1
                elif ok is False and not denied:
                    session["tool_errors"] += 1
                if name in {"write_file", "shell"}:
                    if isinstance(approval, str) and approval in {"approved", "denied"}:
                        session["approval_requests"] += 1
                        if approval == "approved":
                            session["approval_approvals"] += 1
                        else:
                            session["approval_denials"] += 1
                    elif approval != "not_requested":
                        if legacy_denial:
                            session["approval_requests"] += 1
                            session["approval_denials"] += 1
                        else:
                            session["approval_data_complete"] = False
                if denied:
                    session["tool_denials"] += 1
                seconds = _nonnegative_number(data.get("seconds"))
                if seconds is not None:
                    tool_seconds += seconds
                    timed_tool_calls += 1
                _push_timeline(session, {
                    "event": "tool",
                    "step": _nonnegative_int(data.get("step")),
                    "name": name,
                    "ok": ok,
                    "denied": denied,
                    "approval": approval if isinstance(approval, str)
                    and approval in {"approved", "denied", "not_requested"} else None,
                    "seconds": _round_or_none(seconds),
                })
            elif event_name == "finish":
                status = data.get("status")
                session["status"] = status if isinstance(status, str) and status in STATUSES else "unknown"
                steps = _nonnegative_int(data.get("steps"))
                if steps is not None:
                    session["agent_steps"] = steps
                finish_time = event_time or finish_time
                _push_timeline(session, {
                    "event": "finish",
                    "status": session["status"],
                    "steps": steps,
                })
            elif event_name == "error":
                error_type = data.get("type")
                if isinstance(error_type, str) and ERROR_TYPE_RE.fullmatch(error_type):
                    session["error_type"] = error_type
                if session["status"] == "incomplete":
                    session["status"] = "error"
                _push_timeline(session, {"event": "error", "type": session["error_type"]})

    if session["status"] == "incomplete" and session["error_type"]:
        session["status"] = "error"
    if not session["approval_data_complete"]:
        for field in ("approval_requests", "approval_approvals", "approval_denials"):
            session[field] = None
    if session["agent_steps"] == 0:
        session["agent_steps"] = assistant_steps
    session["assistant_seconds"] = _round_or_none(assistant_seconds) or 0.0
    session["tool_seconds"] = _round_or_none(tool_seconds) if timed_tool_calls else None
    session["timed_tool_calls"] = timed_tool_calls
    session["tool_counts"] = dict(sorted(tool_counts.items()))
    for field in TOKEN_FIELDS:
        session[field] = token_sums[field] if token_observations[field] else None
    if first_time is not None:
        session["start_time_utc"] = session["start_time_utc"] or _timestamp_text(first_time)
    end_time = finish_time or last_time
    session["end_time_utc"] = _timestamp_text(end_time)
    if first_time is not None and end_time is not None:
        duration = (end_time - first_time).total_seconds()
        session["duration_seconds"] = _round_or_none(duration) if duration >= 0 else None
    return session


def _median(values):
    return _round_or_none(statistics.median(values)) if values else None


def aggregate_sessions(sessions):
    statuses = Counter(session["status"] for session in sessions)
    durations = [session["duration_seconds"] for session in sessions
                 if session["duration_seconds"] is not None]
    steps = [session["agent_steps"] for session in sessions]
    assistant_times = [session["assistant_seconds"] for session in sessions]
    tool_times = [session["tool_seconds"] for session in sessions
                  if session["tool_seconds"] is not None]
    tool_calls = sum(session["tool_calls"] for session in sessions)
    tool_errors = sum(session["tool_errors"] for session in sessions)
    tool_denials = sum(session["tool_denials"] for session in sessions)
    tool_execution_attempts = max(tool_calls - tool_denials, 0)
    completed = statuses.get("completed", 0)
    count = len(sessions)
    task_outcomes = Counter(session.get("task_outcome") for session in sessions
                            if session.get("task_outcome"))
    verified = [session.get("independent_verification") for session in sessions
                if session.get("independent_verification") in {"passed", "failed"}]
    verified_passes = sum(result == "passed" for result in verified)
    approval_data_complete_sessions = sum(
        bool(session["approval_data_complete"]) for session in sessions)
    approval_data_complete = approval_data_complete_sessions == count
    return {
        "session_count": count,
        "status_counts": dict(sorted(statuses.items())),
        "task_outcome_counts": dict(sorted(task_outcomes.items())),
        "independently_verified_sessions": len(verified),
        "independent_verification_passes": verified_passes,
        "independent_verification_rate": _round_or_none(verified_passes / len(verified))
        if verified else None,
        "completed_count": completed,
        "completed_rate": _round_or_none(completed / count) if count else None,
        "median_duration_seconds": _median(durations),
        "median_agent_steps": _median(steps),
        "median_assistant_seconds": _median(assistant_times),
        "median_tool_seconds": _median(tool_times),
        "tool_calls": tool_calls,
        "tool_execution_attempts": tool_execution_attempts,
        "tool_errors": tool_errors,
        "tool_error_rate": _round_or_none(tool_errors / tool_execution_attempts)
        if tool_execution_attempts else None,
        "tool_denials": tool_denials,
        "approval_data_complete_sessions": approval_data_complete_sessions,
        "approval_data_incomplete_sessions": count - approval_data_complete_sessions,
        "approval_requests": sum(session["approval_requests"] or 0 for session in sessions)
        if approval_data_complete else None,
        "approval_approvals": sum(session["approval_approvals"] or 0 for session in sessions)
        if approval_data_complete else None,
        "approval_denials": sum(session["approval_denials"] or 0 for session in sessions)
        if approval_data_complete else None,
        "token_usage_observed_sessions": sum(
            1 for session in sessions if any(session[field] is not None for field in TOKEN_FIELDS)),
        "note": "completed_rate 表示 Agent 正常完成率，不代表任务正确率；仅当导入 passed/failed 验证标签时才计算 independent_verification_rate。",
    }


def _survey_cell(row, indexes, name):
    index = indexes.get(name)
    return row[index].strip() if index is not None and index < len(row) else ""


def read_survey_csv(path):
    """Read only fixed labels/ratings; free-text and unknown columns are discarded."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("问卷 CSV 必须是普通文件")
    records = {}
    invalid_rows = 0
    invalid_answers = 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("问卷 CSV 为空")
        if len(header) != len(set(header)) or "session_id" not in header:
            raise ValueError("问卷 CSV 必须有不重复列名，并包含 session_id")
        indexes = {name: index for index, name in enumerate(header)}
        for row in reader:
            session_id = _survey_cell(row, indexes, "session_id")
            if not SESSION_RE.fullmatch(session_id):
                invalid_rows += 1
                continue
            if session_id in records:
                raise ValueError("问卷 CSV 中 session_id 重复")
            item = {}
            for field in LABEL_FIELDS:
                raw_label = _survey_cell(row, indexes, field)
                item[field] = _label(raw_label)
                if raw_label and item[field] is None:
                    invalid_answers += 1
            item["task_outcome"] = None
            raw_outcome = _survey_cell(row, indexes, "task_outcome")
            if raw_outcome:
                if raw_outcome in TASK_OUTCOMES:
                    item["task_outcome"] = raw_outcome
                else:
                    invalid_answers += 1
            item["independent_verification"] = None
            raw_verification = _survey_cell(row, indexes, "independent_verification")
            if raw_verification:
                if raw_verification in VERIFICATION_RESULTS:
                    item["independent_verification"] = raw_verification
                else:
                    invalid_answers += 1
            ratings = {}
            for field in QUESTION_FIELDS:
                raw = _survey_cell(row, indexes, field)
                if not raw or raw.lower() in {"na", "n/a", "不适用"}:
                    continue
                if raw not in {"1", "2", "3", "4", "5"}:
                    invalid_answers += 1
                    continue
                ratings[field] = int(raw)
            friction_raw = _survey_cell(row, indexes, "friction_tags")
            friction = sorted({tag.strip().lower() for tag in friction_raw.split(";")
                               if tag.strip().lower() in FRICTION_CODES})
            if friction_raw:
                invalid_answers += sum(1 for tag in friction_raw.split(";")
                                       if tag.strip() and tag.strip().lower() not in FRICTION_CODES)
            item["ratings"] = ratings
            item["friction_tags"] = friction
            records[session_id] = item
    return records, {"invalid_rows": invalid_rows, "invalid_answers": invalid_answers}


def _survey_summary(sessions):
    rating_values = {field: [] for field in QUESTION_FIELDS}
    friction_counts = Counter()
    outcome_counts = Counter()
    verification_counts = Counter()
    response_count = 0
    for session in sessions:
        ratings = session.get("ratings", {})
        tags = session.get("friction_tags", [])
        if ratings or tags or session.get("task_outcome") or session.get("independent_verification"):
            response_count += 1
        if session.get("task_outcome"):
            outcome_counts[session["task_outcome"]] += 1
        if session.get("independent_verification"):
            verification_counts[session["independent_verification"]] += 1
        for field in QUESTION_FIELDS:
            if field in ratings:
                rating_values[field].append(ratings[field])
        friction_counts.update(tags)
    items = {}
    for field, values in rating_values.items():
        items[field] = {
            "responses": len(values),
            "median": _median(values),
            "distribution": {str(value): values.count(value) for value in range(1, 6)},
        }
    return {
        "responses_with_ratings_or_tags_or_outcomes": response_count,
        "task_outcome_counts": dict(sorted(outcome_counts.items())),
        "independent_verification_counts": dict(sorted(verification_counts.items())),
        "items": items,
        "friction_tag_counts": dict(sorted(friction_counts.items())),
    }


def _merge_survey(sessions, survey_records):
    by_id = {session["session_id"]: session for session in sessions}
    unmatched = 0
    conflicts = 0
    for session_id, survey in survey_records.items():
        session = by_id.get(session_id)
        if session is None:
            unmatched += 1
            continue
        for field in LABEL_FIELDS:
            value = survey.get(field)
            if not value:
                continue
            if session.get(field) and session[field] != value:
                conflicts += 1
            elif not session.get(field):
                session[field] = value
        session["task_outcome"] = survey.get("task_outcome")
        session["independent_verification"] = survey.get("independent_verification")
        session["ratings"] = survey["ratings"]
        session["friction_tags"] = survey["friction_tags"]
    return {"rows_unmatched_to_trace": unmatched, "label_conflicts": conflicts}


def build_report(sessions, *, trace_files_found, trace_files_skipped=0,
                 survey_input=None, survey_issues=None):
    sessions = sorted(sessions, key=lambda item: (item.get("start_time_utc") or "",
                                                   item["session_id"]))
    by_category = defaultdict(list)
    by_config = defaultdict(list)
    for session in sessions:
        category = session.get("task_category")
        config_id = session.get("config_id")
        if category:
            by_category[category].append(session)
        if config_id:
            by_config[config_id].append(session)
    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": {
            "trace_files_found": trace_files_found,
            "trace_sessions_included": len(sessions),
            "trace_files_skipped": trace_files_skipped,
            "malformed_trace_lines": sum(session["trace_issue_count"] for session in sessions),
        },
        "summary": aggregate_sessions(sessions),
        "by_task_category": {category: aggregate_sessions(group)
                             for category, group in sorted(by_category.items())},
        "by_config_id": {config_id: aggregate_sessions(group)
                         for config_id, group in sorted(by_config.items())},
        "survey": _survey_summary(sessions) if survey_input else None,
        "survey_input": ({**(survey_issues or {}), **survey_input} if survey_input else None),
        "privacy": {
            "raw_prompts_exported": False,
            "assistant_content_exported": False,
            "tool_arguments_or_results_exported": False,
            "reasoning_or_free_text_exported": False,
            "model_alias_exported": False,
        },
        "sessions": sessions,
    }
    return report


CSV_FIELDS = [
    "session_id", "start_time_utc", "end_time_utc", "duration_seconds", "status",
    "task_id", "task_category", "config_id", "task_outcome", "independent_verification",
    "agent_steps", "assistant_seconds",
    "tool_seconds", "timed_tool_calls", "tool_calls", "tool_successes", "tool_errors",
    "tool_denials", "approval_requests", "approval_approvals", "approval_denials",
    "tool_counts", *TOKEN_FIELDS, *QUESTION_FIELDS, "friction_tags",
    "error_type", "trace_issue_count", "timeline_truncated",
]


def render_csv(sessions):
    import io
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for session in sessions:
        row = {key: session.get(key) for key in CSV_FIELDS}
        row["tool_counts"] = json.dumps(session.get("tool_counts", {}), sort_keys=True)
        for field in QUESTION_FIELDS:
            row[field] = session.get("ratings", {}).get(field, "")
        row["friction_tags"] = ";".join(session.get("friction_tags", []))
        writer.writerow(row)
    return output.getvalue()


def _private_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _discover_traces(runs_dir):
    root = Path(runs_dir)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("runs-dir 必须是已存在的普通目录")
    files = []
    skipped = 0
    for path in sorted(root.glob("*.jsonl")):
        if path.is_symlink() or not path.is_file():
            skipped += 1
        else:
            files.append(path)
    return files, skipped


def parser():
    p = argparse.ArgumentParser(
        description="在本机分析 Harness27 JSONL 轨迹；报告只包含脱敏结构化指标，不发送网络请求")
    p.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR),
                   help="Harness27 JSONL 轨迹目录（默认：.harness27/runs）")
    p.add_argument("--survey-csv", help="可选的任务后问卷 CSV；仅读取固定标签、结果枚举、评分和 friction_tags 列")
    p.add_argument("--format", choices=("json", "csv"), default="json",
                   help="JSON 包含汇总与事件序列；CSV 输出逐任务结构化行")
    p.add_argument("--output", help="输出文件；默认写入 .harness27/analytics/，使用 - 写到标准输出")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        trace_files, skipped = _discover_traces(args.runs_dir)
        trace_files_found = len(trace_files) + skipped
        sessions = []
        for path in trace_files:
            try:
                sessions.append(analyze_trace(path))
            except (OSError, UnicodeError):
                skipped += 1
        survey_records = None
        survey_issues = None
        survey_input = None
        if args.survey_csv:
            survey_records, survey_issues = read_survey_csv(args.survey_csv)
            survey_input = _merge_survey(sessions, survey_records)
            survey_input["rows_read"] = len(survey_records)
            survey_input["invalid_rows"] = survey_issues["invalid_rows"]
            survey_input["invalid_answers"] = survey_issues["invalid_answers"]
        report = build_report(sessions, trace_files_found=trace_files_found,
                              trace_files_skipped=skipped, survey_input=survey_input,
                              survey_issues=survey_issues)
        if args.format == "json":
            text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        else:
            text = render_csv(sessions)
        if args.output == "-":
            sys.stdout.write(text)
        else:
            if args.output:
                output_path = Path(args.output)
            else:
                DEFAULT_REPORT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                output_path = DEFAULT_REPORT_DIR / f"analysis-{stamp}-{uuid.uuid4().hex[:8]}.{args.format}"
            resolved_output = output_path.resolve()
            if any(resolved_output == source.resolve() for source in trace_files):
                raise ValueError("分析报告不能覆盖输入轨迹文件")
            if args.survey_csv and resolved_output == Path(args.survey_csv).resolve():
                raise ValueError("分析报告不能覆盖输入问卷文件")
            _private_write(output_path, text)
            print(f"分析报告：{output_path}", file=sys.stderr)
        print(
            f"分析完成：{len(sessions)} 个任务，"
            f"Agent completed={report['summary']['completed_count']}；"
            f"报告只含脱敏结构化指标。",
            file=sys.stderr,
        )
        return 0
    except (OSError, ValueError, csv.Error) as exc:
        print(f"分析失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

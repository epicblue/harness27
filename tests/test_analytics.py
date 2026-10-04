import argparse
import csv
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from harness27.analytics import aggregate_sessions, analyze_trace, main, read_survey_csv, render_csv
from harness27.cli import label_arg, main as cli_main, parser as cli_parser


class RunAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"
        self.runs.mkdir()
        self.session_id = "20261004T120000Z-a1b2c3d4"
        base = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
        times = [base + timedelta(seconds=i) for i in range(5)]
        events = [
            ("start", {"task": "RAW_TASK_SECRET", "model": "private-model-alias",
                       "task_id": "task_01", "task_category": "file_ops", "config_id": "local_a"}),
            ("assistant", {"step": 1, "seconds": 1.25,
                           "message": {"content": "RAW_ANSWER_SECRET", "tool_calls": [
                               {"function": {"arguments": '{"path":"RAW_ARG_SECRET"}'}}]},
                           "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
                           "finish_reason": "tool_calls"}),
            ("tool", {"step": 1, "name": "read_file", "arguments": {"path": "RAW_PATH_SECRET"},
                      "result": {"ok": True, "content": "RAW_FILE_SECRET"}, "seconds": 0.05}),
            ("tool", {"step": 1, "name": "write_file", "arguments": {"content": "RAW_WRITE_SECRET"},
                      "result": {"ok": False, "error": "用户拒绝写入", "approval": "denied"},
                      "seconds": 0.01}),
            ("tool", {"step": 1, "name": "write_file", "arguments": {"content": "RAW_WRITE_APPROVED_SECRET"},
                      "result": {"ok": True, "bytes_written": 12, "approval": "approved"},
                      "seconds": 0.02}),
            ("assistant", {"step": 2, "seconds": 0.5,
                           "message": {"content": "RAW_FINAL_SECRET"}, "finish_reason": "stop"}),
            ("finish", {"status": "completed", "answer": "RAW_FINAL_SECRET", "steps": 2}),
        ]
        trace = self.runs / f"{self.session_id}.jsonl"
        with trace.open("w", encoding="utf-8") as stream:
            for i, (event, data) in enumerate(events):
                record = {"trace_schema_version": 1,
                          "time": times[min(i, len(times) - 1)].isoformat(),
                          "event": event, **data}
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.write("{not valid json\n")
        self.trace_path = trace

    def tearDown(self):
        self.temp.cleanup()

    def test_analysis_keeps_process_metrics_but_drops_raw_content(self):
        session = analyze_trace(self.trace_path)
        self.assertEqual(session["session_id"], self.session_id)
        self.assertEqual(session["status"], "completed")
        self.assertEqual(session["agent_steps"], 2)
        self.assertEqual(session["tool_calls"], 3)
        self.assertEqual(session["tool_successes"], 2)
        self.assertEqual(session["tool_errors"], 0)
        self.assertEqual(session["tool_denials"], 1)
        self.assertEqual(session["approval_requests"], 2)
        self.assertEqual(session["approval_approvals"], 1)
        self.assertEqual(session["approval_denials"], 1)
        self.assertEqual(session["tool_counts"], {"read_file": 1, "write_file": 2})
        self.assertAlmostEqual(session["assistant_seconds"], 1.75)
        self.assertAlmostEqual(session["tool_seconds"], 0.08)
        self.assertEqual(session["prompt_tokens"], 11)
        self.assertEqual(session["total_tokens"], 15)
        self.assertEqual(session["task_category"], "file_ops")
        self.assertEqual(session["trace_issue_count"], 1)
        self.assertEqual(aggregate_sessions([session])["tool_execution_attempts"], 2)
        self.assertEqual(aggregate_sessions([session])["tool_error_rate"], 0.0)
        self.assertEqual(len(session["timeline"]), 7)
        serialized = json.dumps(session, ensure_ascii=False)
        for secret in ("RAW_TASK_SECRET", "RAW_ANSWER_SECRET", "RAW_ARG_SECRET",
                       "RAW_PATH_SECRET", "RAW_FILE_SECRET", "RAW_WRITE_SECRET",
                       "RAW_WRITE_APPROVED_SECRET", "RAW_FINAL_SECRET", "private-model-alias"):
            self.assertNotIn(secret, serialized)

    def test_survey_join_ignores_free_text_and_writes_private_report(self):
        survey_path = self.root / "survey.csv"
        with survey_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "session_id", "task_id", "task_category", "config_id", "task_outcome",
                "independent_verification", "q1_start_clarity", "q2_progress_visibility",
                "q7_reuse", "friction_tags", "comments",
            ])
            writer.writeheader()
            writer.writerow({
                "session_id": self.session_id,
                "task_id": "task_01",
                "task_category": "file_ops",
                "config_id": "local_a",
                "task_outcome": "completed",
                "independent_verification": "passed",
                "q1_start_clarity": "4",
                "q2_progress_visibility": "5",
                "q7_reuse": "3",
                "friction_tags": "tool_call;docs;unknown_tag",
                "comments": "RAW_SURVEY_COMMENT_SECRET",
            })
        report_path = self.root / "analytics" / "report.json"
        result = main(["--runs-dir", str(self.runs), "--survey-csv", str(survey_path),
                       "--output", str(report_path)])
        self.assertEqual(result, 0)
        report_text = report_path.read_text(encoding="utf-8")
        report = json.loads(report_text)
        self.assertEqual(report["summary"]["completed_count"], 1)
        self.assertEqual(report["summary"]["completed_rate"], 1.0)
        self.assertEqual(report["summary"]["independent_verification_rate"], 1.0)
        self.assertEqual(report["summary"]["task_outcome_counts"], {"completed": 1})
        self.assertEqual(report["survey"]["items"]["q1_start_clarity"]["median"], 4)
        self.assertEqual(report["survey"]["friction_tag_counts"], {"docs": 1, "tool_call": 1})
        self.assertEqual(report["survey_input"]["invalid_answers"], 1)
        self.assertFalse(report["privacy"]["raw_prompts_exported"])
        self.assertNotIn("RAW_SURVEY_COMMENT_SECRET", report_text)
        self.assertNotIn("RAW_TASK_SECRET", report_text)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(report_path.stat().st_mode), 0o600)

    def test_csv_export_contains_only_allowlisted_session_fields(self):
        session = analyze_trace(self.trace_path)
        output = render_csv([session])
        self.assertIn("session_id,start_time_utc,end_time_utc,duration_seconds,status,", output)
        for secret in ("RAW_TASK_SECRET", "RAW_FILE_SECRET", "RAW_ARG_SECRET", "private-model-alias"):
            self.assertNotIn(secret, output)

    def test_cli_labels_are_non_sensitive_slugs(self):
        self.assertEqual(label_arg("task_01"), "task_01")
        with self.assertRaises(argparse.ArgumentTypeError):
            label_arg("private task text")
        args = cli_parser().parse_args([
            "--model", "local", "--task-id", "task_01", "--task-category", "file_ops",
            "--config-id", "local_a", "示例任务",
        ])
        self.assertEqual(args.task_category, "file_ops")
        self.assertEqual(args.config_id, "local_a")

    def test_cli_records_versioned_run_labels_for_analysis(self):
        class FakeClient:
            def __init__(self, base_url, model, *args):
                self.model = model

            def complete(self, messages, tools):
                return {"role": "assistant", "content": "已完成"}

        previous_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            with patch("harness27.cli.LocalClient", FakeClient), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                result = cli_main([
                    "--model", "private-model-alias", "--task-id", "task_01",
                    "--task-category", "file_ops", "--config-id", "local_a",
                    "--workspace", str(self.root / "workspace"), "raw task text",
                ])
            self.assertEqual(result, 0)
            trace_path = next((self.root / ".harness27" / "runs").glob("*.jsonl"))
            events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(all(event["trace_schema_version"] == 1 for event in events))
            start = next(event for event in events if event["event"] == "start")
            self.assertEqual(start["task_id"], "task_01")
            self.assertEqual(start["task_category"], "file_ops")
            self.assertEqual(start["config_id"], "local_a")
            analyzed = analyze_trace(trace_path)
            self.assertEqual(analyzed["status"], "completed")
            self.assertEqual(analyzed["task_category"], "file_ops")
        finally:
            os.chdir(previous_cwd)

    def test_legacy_trace_does_not_invent_approval_counts(self):
        legacy = self.runs / "20261004T120100Z-a1b2c3d5.jsonl"
        records = [
            {"event": "start", "time": "2026-10-04T12:01:00Z", "task": "secret"},
            {"event": "tool", "time": "2026-10-04T12:01:01Z", "step": 1,
             "name": "write_file", "result": {"ok": True, "bytes_written": 1}},
            {"event": "finish", "time": "2026-10-04T12:01:02Z", "status": "completed", "steps": 1},
        ]
        legacy.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
        session = analyze_trace(legacy)
        self.assertFalse(session["approval_data_complete"])
        self.assertIsNone(session["approval_approvals"])
        summary = aggregate_sessions([session])
        self.assertEqual(summary["approval_data_incomplete_sessions"], 1)
        self.assertIsNone(summary["approval_approvals"])

    def test_survey_duplicate_session_id_is_rejected(self):
        survey_path = self.root / "duplicate.csv"
        survey_path.write_text(
            "session_id,q1_start_clarity\n" + self.session_id + ",4\n" + self.session_id + ",5\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "session_id 重复"):
            read_survey_csv(survey_path)


if __name__ == "__main__":
    unittest.main()

from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from benchmark.compare import compare_reports, main


HARNESS_A = "a" * 64
CASE_A = "b" * 64
CASE_B = "c" * 64
CASE_NAME = "case_12_oee_shift_report"


def result(*, trial, status, fingerprint=CASE_A, agent_status="completed",
           steps=2, elapsed=1.0, tool_errors=0, token_usage=None, **extra):
    row = {
        "case": CASE_NAME,
        "fingerprint_sha256": fingerprint,
        "trial": trial,
        "status": status,
        "agent_status": agent_status,
        "steps_used": steps,
        "elapsed_seconds": elapsed,
        "tool_errors": tool_errors,
        "token_usage": token_usage or {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        },
    }
    row.update(extra)
    return row


def report(run_id, rows, *, harness=HARNESS_A, config=None, status="completed", **extra):
    data = {
        "schema_version": 1,
        "run_id": run_id,
        "status": status,
        "harness_fingerprint_sha256": harness,
        "config": config or {"model": "local-model", "temperature": 0.2},
        "results": rows,
    }
    data.update(extra)
    return data


class BenchmarkCompareTests(unittest.TestCase):
    def test_compares_matched_cases_and_reports_deltas(self):
        baseline = report("baseline-001", [
            result(trial=1, status="passed", steps=2, elapsed=4.0,
                   token_usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}),
            result(trial=2, status="failed", agent_status="step_limit",
                   steps=4, elapsed=8.0, tool_errors=1,
                   token_usage={"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}),
        ])
        candidate = report("candidate-002", [
            result(trial=1, status="passed", steps=2, elapsed=2.0,
                   token_usage={"prompt_tokens": 110, "completion_tokens": 30, "total_tokens": 140}),
            result(trial=2, status="passed", steps=3, elapsed=4.0,
                   token_usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}),
        ], config={"model": "candidate-model", "temperature": 0.2})

        comparison = compare_reports(baseline, candidate)
        case = comparison["case_comparisons"][0]
        self.assertTrue(case["comparable"])
        self.assertEqual(case["baseline"]["success_rate"], 0.5)
        self.assertEqual(case["candidate"]["success_rate"], 1.0)
        self.assertEqual(case["delta"]["success_rate_percentage_points"], 50.0)
        self.assertEqual(case["delta"]["verified_passes"], 1)
        self.assertEqual(case["delta"]["mean_elapsed_seconds"], -3.0)
        self.assertEqual(case["baseline"]["token_usage"]["total_tokens"], 220)
        self.assertEqual(case["candidate"]["token_usage"]["total_tokens"], 260)
        self.assertEqual(case["delta"]["token_usage"]["total_tokens"], 40)
        self.assertEqual(case["delta"]["token_usage"]["mean_total_tokens"], 20.0)
        self.assertEqual(comparison["compatibility"]["changed_config_keys"], ["model"])
        self.assertEqual(comparison["matched_summary"]["baseline"]["attempts"], 2)

    def test_changed_case_definition_is_shown_but_not_scored_as_a_delta(self):
        baseline = report("baseline-001", [result(trial=1, status="passed")])
        candidate = report("candidate-002", [
            result(trial=1, status="failed", fingerprint=CASE_B),
        ])

        comparison = compare_reports(baseline, candidate)
        case = comparison["case_comparisons"][0]
        self.assertFalse(case["case_definition_unchanged"])
        self.assertFalse(case["comparable"])
        self.assertIsNone(case["delta"]["success_rate_percentage_points"])
        self.assertEqual(comparison["compatibility"]["changed_case_definitions"], [CASE_NAME])
        self.assertEqual(comparison["matched_summary"]["delta"]["verified_passes"], None)

    def test_changed_harness_prevents_comparable_deltas(self):
        baseline = report("baseline-001", [result(trial=1, status="passed")])
        candidate = report("candidate-002", [result(trial=1, status="failed")],
                           harness="d" * 64)

        comparison = compare_reports(baseline, candidate)
        case = comparison["case_comparisons"][0]
        self.assertTrue(case["case_definition_unchanged"])
        self.assertFalse(case["comparable"])
        self.assertFalse(comparison["compatibility"]["harness_unchanged"])
        self.assertIsNone(case["delta"]["verified_passes"])

    def test_missing_usage_is_not_reported_as_zero_tokens(self):
        comparison = compare_reports(
            report("baseline-001", [result(trial=1, status="passed")]),
            report("candidate-002", [result(trial=1, status="passed")]),
        )
        metrics = comparison["case_comparisons"][0]["baseline"]["token_usage"]
        self.assertEqual(metrics["observed_trials"], 0)
        self.assertIsNone(metrics["total_tokens"])
        self.assertIsNone(comparison["case_comparisons"][0]["delta"]["token_usage"]["total_tokens"])
        self.assertTrue(any("Token usage may be unavailable" in warning
                            for warning in comparison["warnings"]))

    def test_incomplete_reports_show_metrics_but_do_not_claim_deltas(self):
        baseline = report("baseline-001", [result(trial=1, status="passed")],
                          status="interrupted")
        candidate = report("candidate-002", [result(trial=1, status="failed")])

        comparison = compare_reports(baseline, candidate)
        case = comparison["case_comparisons"][0]
        self.assertEqual(comparison["baseline_report_status"], "interrupted")
        self.assertEqual(comparison["candidate_report_status"], "completed")
        self.assertFalse(comparison["compatibility"]["both_reports_completed"])
        self.assertEqual(case["baseline"]["attempts"], 1)
        self.assertEqual(case["candidate"]["attempts"], 1)
        self.assertFalse(case["comparable"])
        self.assertIsNone(case["delta"]["verified_passes"])
        self.assertTrue(any("partial results" in warning
                            for warning in comparison["warnings"]))

    def test_allowlisted_export_omits_raw_content_and_unknown_fields(self):
        sentinels = [
            "PROMPT_SENTINEL_42", "ANSWER_SENTINEL_42", "REASONING_SENTINEL_42",
            "ARGUMENTS_SENTINEL_42", "TOOL_RESULT_SENTINEL_42",
            "VERIFIER_OUTPUT_SENTINEL_42", "MODEL_ALIAS_SENTINEL_42",
            "BASE_URL_SENTINEL_42",
        ]
        sensitive_fields = {
            "raw_prompt": sentinels[0],
            "model_answer": sentinels[1],
            "reasoning": sentinels[2],
            "tool_arguments": {"payload": sentinels[3]},
            "tool_results": {"content": sentinels[4]},
            "verification_output": {"stdout": sentinels[5]},
            "unknown_extension": "UNKNOWN_SENTINEL_42",
        }
        baseline = report(
            "baseline-001", [result(trial=1, status="passed", **sensitive_fields)],
            config={"model": sentinels[6], "base_url": sentinels[7]},
            raw_prompt=sentinels[0],
        )
        candidate = report("candidate-002", [result(trial=1, status="passed")])

        serialized = json.dumps(compare_reports(baseline, candidate), ensure_ascii=False)
        for sentinel in sentinels:
            self.assertNotIn(sentinel, serialized)
        for field in ("raw_prompt", "model_answer", "reasoning", "tool_arguments",
                      "tool_results", "verification_output", "unknown_extension"):
            self.assertNotIn(f'"{field}"', serialized)

    def test_rejects_invalid_case_names_and_duplicate_trials(self):
        invalid_name = report("baseline-001", [
            dict(result(trial=1, status="passed"), case="../private"),
        ])
        with self.assertRaisesRegex(ValueError, "invalid case name"):
            compare_reports(invalid_name, report("candidate-002", []))

        duplicate_trials = report("baseline-001", [
            result(trial=1, status="passed"),
            result(trial=1, status="failed"),
        ])
        with self.assertRaisesRegex(ValueError, "duplicate case/trial"):
            compare_reports(duplicate_trials, report("candidate-002", []))

        invalid_status = report("baseline-001", [], status="in_progress")
        with self.assertRaisesRegex(ValueError, "invalid run status"):
            compare_reports(invalid_status, report("candidate-002", []))

    def test_cli_writes_a_private_comparison_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / "baseline.json"
            candidate_path = root / "candidate.json"
            output_path = root / "private" / "comparison.json"
            baseline_path.write_text(json.dumps(report(
                "baseline-001", [result(trial=1, status="passed", raw_prompt="DO_NOT_EXPORT")]
            )), encoding="utf-8")
            candidate_path.write_text(json.dumps(report(
                "candidate-002", [result(trial=1, status="failed")]
            )), encoding="utf-8")

            self.assertEqual(main([
                "--baseline", str(baseline_path),
                "--candidate", str(candidate_path),
                "--output", str(output_path),
            ]), 0)
            serialized = output_path.read_text(encoding="utf-8")
            self.assertNotIn("DO_NOT_EXPORT", serialized)
            self.assertEqual(json.loads(serialized)["comparison_schema_version"], 1)
            if os.name == "posix":
                self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)

            error_output = io.StringIO()
            with redirect_stderr(error_output):
                exit_code = main([
                    "--baseline", str(baseline_path),
                    "--candidate", str(candidate_path),
                    "--output", str(baseline_path),
                ])
            self.assertEqual(exit_code, 2)
            self.assertIn("must not replace either input report", error_output.getvalue())
            self.assertIn("DO_NOT_EXPORT", baseline_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

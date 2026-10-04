import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark import runner


class FakeClient:
    model = "test-27b"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append((list(messages), list(tools)))
        return next(self.responses)


def call(call_id, name, arguments):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }],
    }


class BenchmarkRunnerTests(unittest.TestCase):
    def setUp(self):
        self.cases = {case.name: case for case in runner.discover_cases()}

    def test_discovery_and_path_traversal_rejection(self):
        self.assertEqual(len(self.cases), 7)
        for case in self.cases.values():
            self.assertEqual(len(case.fingerprint), 64)
        with self.assertRaises(ValueError):
            runner.discover_cases(["../README"])
        with self.assertRaises(ValueError):
            runner.discover_cases(["case_does_not_exist"])

    def test_csv_case_runs_and_emits_objective_metrics(self):
        rows = [
            {"invoice_id": "INV-1001", "customer": "Northwind", "billed_amount": 1200.00,
             "paid_amount": 1200.00, "outstanding_amount": 0, "status": "paid"},
            {"invoice_id": "INV-1002", "customer": "Acme", "billed_amount": 450.50,
             "paid_amount": 299.50, "outstanding_amount": 151, "status": "partial"},
            {"invoice_id": "INV-1003", "customer": "Globex", "billed_amount": 300,
             "paid_amount": 100, "outstanding_amount": 200, "status": "partial"},
            {"invoice_id": "INV-1004", "customer": "Initech", "billed_amount": 75,
             "paid_amount": 0, "outstanding_amount": 75, "status": "unpaid"},
        ]
        client = FakeClient([
            call("write-1", "write_file", {
                "path": "reconciliation.json",
                "content": json.dumps(rows),
            }),
            {"role": "assistant", "content": "已完成对账。",
             "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}},
        ])
        row = runner.run_case(
            self.cases["case_04_csv_reconciliation"], client, "test-run", 1,
            max_steps=4,
        )
        self.assertEqual(row["status"], "passed")
        self.assertEqual(row["agent_status"], "completed")
        self.assertEqual(row["tool_names"], {"write_file": 1})
        self.assertEqual(row["token_usage"]["total_tokens"], 150)
        self.assertIsNone(row["workspace"])
        self.assertEqual(list((runner.DATA_ROOT / "workspaces").glob(
            "case_04_csv_reconciliation-trial-01-*")), [])

    def test_inventory_case_has_a_complete_testable_user_story(self):
        metadata = self.cases["case_05_warehouse_replenishment"].metadata
        story = metadata["user_story"]
        self.assertEqual(set(story), {"as_a", "i_want", "so_that"})
        self.assertTrue(all(isinstance(value, str) and value.strip()
                            for value in story.values()))
        criteria = metadata["acceptance_criteria"]
        self.assertEqual([item["id"] for item in criteria],
                         ["AC-01", "AC-02", "AC-03", "AC-04", "AC-05"])
        self.assertTrue(all(item.get("requirement") for item in criteria))
        self.assertTrue(metadata["out_of_scope"])
        self.assertEqual(metadata["shell"], "disabled")

    def test_inventory_replenishment_case_runs_without_shell(self):
        rows = [
            {"sku": "SKU-A", "on_hand": 12, "open_order_units": 13,
             "available_units": 25, "target_stock": 40, "recommended_order_qty": 15},
            {"sku": "SKU-B", "on_hand": 5, "open_order_units": 7,
             "available_units": 12, "target_stock": 20, "recommended_order_qty": 8},
            {"sku": "SKU-D", "on_hand": 0, "open_order_units": 0,
             "available_units": 0, "target_stock": 12, "recommended_order_qty": 12},
            {"sku": "SKU-F", "on_hand": 8, "open_order_units": 4,
             "available_units": 12, "target_stock": 16, "recommended_order_qty": 4},
        ]
        client = FakeClient([
            call("write-1", "write_file", {
                "path": "reorder_plan.json",
                "content": json.dumps(rows),
            }),
            {"role": "assistant", "content": "补货建议已生成。",
             "usage": {"prompt_tokens": 140, "completion_tokens": 24, "total_tokens": 164}},
        ])
        row = runner.run_case(
            self.cases["case_05_warehouse_replenishment"], client, "test-run", 1,
            max_steps=4, allow_shell=True,
        )
        self.assertEqual(row["status"], "passed")
        self.assertEqual(row["agent_status"], "completed")
        self.assertEqual(row["tool_names"], {"write_file": 1})
        self.assertEqual(row["token_usage"]["total_tokens"], 164)
        schemas = {item["function"]["name"] for item in client.requests[0][1]}
        self.assertNotIn("shell", schemas)

    def test_install_plan_case_has_a_complete_testable_user_story(self):
        metadata = self.cases["case_06_ordered_package_install_plan"].metadata
        story = metadata["user_story"]
        self.assertEqual(set(story), {"as_a", "i_want", "so_that"})
        self.assertTrue(all(isinstance(value, str) and value.strip()
                            for value in story.values()))
        criteria = metadata["acceptance_criteria"]
        self.assertEqual([item["id"] for item in criteria],
                         ["AC-01", "AC-02", "AC-03", "AC-04", "AC-05"])
        self.assertTrue(all(item.get("requirement") for item in criteria))
        self.assertTrue(metadata["out_of_scope"])
        self.assertEqual(metadata["shell"], "disabled")

    def test_ordered_package_plan_runs_without_exposing_shell(self):
        order = [
            ("acme-common", "2.4.1"),
            ("acme-auth", "1.7.0"),
            ("acme-config", "1.3.2"),
            ("acme-http", "3.2.0"),
            ("acme-client", "4.0.0"),
            ("acme-metrics", "1.5.0"),
            ("acme-report", "2.1.5"),
            ("daily-close", "0.9.3"),
        ]
        plan = [{"step": step, "package": name, "version": version}
                for step, (name, version) in enumerate(order, start=1)]
        client = FakeClient([
            call("write-1", "write_file", {
                "path": "install_plan.json",
                "content": json.dumps(plan),
            }),
            {"role": "assistant", "content": "已生成待审核的安装顺序计划。"},
        ])
        row = runner.run_case(
            self.cases["case_06_ordered_package_install_plan"], client, "test-run", 1,
            max_steps=4, allow_shell=True,
        )
        self.assertEqual(row["status"], "passed")
        self.assertEqual(row["tool_names"], {"write_file": 1})
        schemas = {item["function"]["name"] for item in client.requests[0][1]}
        self.assertNotIn("shell", schemas)

    def test_support_ticket_case_has_a_complete_testable_user_story(self):
        metadata = self.cases["case_07_support_ticket_triage"].metadata
        story = metadata["user_story"]
        self.assertEqual(set(story), {"as_a", "i_want", "so_that"})
        self.assertTrue(all(isinstance(value, str) and value.strip()
                            for value in story.values()))
        criteria = metadata["acceptance_criteria"]
        self.assertEqual([item["id"] for item in criteria],
                         ["AC-01", "AC-02", "AC-03", "AC-04", "AC-05"])
        self.assertTrue(all(item.get("requirement") for item in criteria))
        self.assertTrue(metadata["out_of_scope"])
        self.assertEqual(metadata["shell"], "disabled")

    def test_support_ticket_triage_runner_path_without_shell(self):
        rows = [
            {"ticket_id": "T-101", "queue": "identity_ops", "priority": "P1",
             "first_response_due_utc": "2026-10-04T09:00:00Z"},
            {"ticket_id": "T-104", "queue": "finance_ops", "priority": "P1",
             "first_response_due_utc": "2026-10-04T12:00:00Z"},
            {"ticket_id": "T-102", "queue": "finance_ops", "priority": "P2",
             "first_response_due_utc": "2026-10-04T16:15:00Z"},
            {"ticket_id": "T-103", "queue": "data_platform", "priority": "P3",
             "first_response_due_utc": "2026-10-04T17:30:00Z"},
            {"ticket_id": "T-105", "queue": "identity_ops", "priority": "P3",
             "first_response_due_utc": "2026-10-05T11:45:00Z"},
        ]
        client = FakeClient([
            call("write-1", "write_file", {
                "path": "triage_plan.json",
                "content": json.dumps(rows),
            }),
            {"role": "assistant", "content": "已整理供人工分派的工单清单。"},
        ])
        row = runner.run_case(
            self.cases["case_07_support_ticket_triage"], client, "test-run", 1,
            max_steps=4, allow_shell=True,
        )
        self.assertEqual(row["status"], "passed")
        self.assertEqual(row["agent_status"], "completed")
        self.assertEqual(row["tool_names"], {"write_file": 1})
        schemas = {item["function"]["name"] for item in client.requests[0][1]}
        self.assertNotIn("shell", schemas)

    def test_forbidden_read_attempt_fails_even_when_output_is_correct(self):
        client = FakeClient([
            call("read-1", "read_file", {"path": "secret.key"}),
            call("write-1", "write_file", {"path": "dead_code.txt", "content": "legacy_unused.py"}),
            {"role": "assistant", "content": "已完成。"},
        ])
        row = runner.run_case(
            self.cases["case_02_negative_constraint"], client, "test-run", 1,
            max_steps=5, allow_shell=True,
        )
        self.assertEqual(row["status"], "failed")
        self.assertFalse(row["verified"])
        exposed_tools = {schema["function"]["name"] for schema in client.requests[0][1]}
        self.assertNotIn("shell", exposed_tools)
        self.assertEqual(row["tool_names"], {"read_file": 1, "write_file": 1})
        self.assertIn("违反否定约束", row["verification_output"]["stderr"])

    def test_inference_errors_are_not_counted_as_capability_failures(self):
        class BrokenClient:
            model = "offline"

            def complete(self, messages, tools):
                raise RuntimeError("simulated connection failure")

        row = runner.run_case(
            self.cases["case_04_csv_reconciliation"], BrokenClient(), "test-run", 1,
        )
        self.assertEqual(row["status"], "error")
        summary = runner.build_summary([row])["overall"]
        self.assertEqual(summary["attempts"], 0)
        self.assertEqual(summary["errors"], 1)

    def test_shell_required_case_is_skipped_without_explicit_opt_in(self):
        client = FakeClient([])
        row = runner.run_case(
            self.cases["case_03_pytest_repair"], client, "test-run", 1,
            allow_shell=False,
        )
        self.assertEqual(row["status"], "skipped")
        self.assertEqual(client.requests, [])

    def test_setup_never_deletes_existing_workspace(self):
        case = self.cases["case_01_read_extract"]
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "workspace"
            target.mkdir()
            marker = target / "keep.txt"
            marker.write_text("preserve me")
            with self.assertRaises(ValueError):
                runner.setup_workspace(case.path, target)
            self.assertEqual(marker.read_text(), "preserve me")

    def test_cli_writes_private_report_without_raw_tool_arguments(self):
        rows = [
            {"invoice_id": "INV-1001", "customer": "Northwind", "billed_amount": 1200,
             "paid_amount": 1200, "outstanding_amount": 0, "status": "paid"},
            {"invoice_id": "INV-1002", "customer": "Acme", "billed_amount": 450.5,
             "paid_amount": 299.5, "outstanding_amount": 151, "status": "partial"},
            {"invoice_id": "INV-1003", "customer": "Globex", "billed_amount": 300,
             "paid_amount": 100, "outstanding_amount": 200, "status": "partial"},
            {"invoice_id": "INV-1004", "customer": "Initech", "billed_amount": 75,
             "paid_amount": 0, "outstanding_amount": 75, "status": "unpaid"},
        ]
        client = FakeClient([
            call("write-1", "write_file", {
                "path": "reconciliation.json", "content": json.dumps(rows),
            }),
            {"role": "assistant", "content": "完成。"},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            with patch.object(runner, "LocalClient", return_value=client):
                exit_code = runner.main([
                    "--case", "case_04_csv_reconciliation",
                    "--model", "test-27b", "--report", str(report_path),
                ])
            self.assertEqual(exit_code, 0)
            report_text = report_path.read_text("utf-8")
            report = json.loads(report_text)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["summary"]["overall"]["success_rate"], 1.0)
            self.assertEqual(len(report["harness_fingerprint_sha256"]), 64)
            self.assertEqual(len(report["results"][0]["fingerprint_sha256"]), 64)
            self.assertNotIn("\"arguments\"", report_text)
            self.assertNotIn("\"content\"", report_text)
            if os.name == "posix":
                self.assertEqual(report_path.stat().st_mode & 0o777, 0o600)

    def test_summary_separates_verification_from_completion(self):
        results = [
            {"status": "passed", "verified": True, "agent_status": "completed",
             "category": "data", "difficulty": "medium", "skills": ["csv"],
             "steps_used": 2, "elapsed_seconds": 1, "tool_calls": 1, "tool_errors": 0,
             "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
            {"status": "failed", "verified": False, "agent_status": "step_limit",
             "category": "data", "difficulty": "medium", "skills": ["csv"],
             "steps_used": 3, "elapsed_seconds": 2, "tool_calls": 2, "tool_errors": 1,
             "token_usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}},
            {"status": "skipped", "verified": None, "agent_status": "not_run",
             "category": "software", "difficulty": "easy", "skills": ["tests"],
             "steps_used": 0, "elapsed_seconds": 0, "tool_calls": 0, "tool_errors": 0,
             "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}},
        ]
        summary = runner.build_summary(results)
        self.assertEqual(summary["overall"]["success_rate"], 0.5)
        self.assertEqual(summary["overall"]["completion_rate"], 0.5)
        self.assertEqual(summary["overall"]["skipped"], 1)
        self.assertEqual(summary["by_skill"]["csv"]["attempts"], 2)
        self.assertEqual(summary["by_category"]["software"]["attempts"], 0)


if __name__ == "__main__":
    unittest.main()

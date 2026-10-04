import json
from pathlib import Path
import shutil
import tempfile
import unittest

from benchmark.cases.case_01_read_extract.verify import verify as verify_case_01
from benchmark.cases.case_02_negative_constraint.verify import verify as verify_case_02
from benchmark.cases.case_03_pytest_repair.verify import verify as verify_case_03
from benchmark.cases.case_04_csv_reconciliation.verify import verify as verify_case_04
from benchmark.cases.case_05_warehouse_replenishment.verify import verify as verify_case_05


CASES = Path(__file__).resolve().parents[1] / "benchmark" / "cases"


class BenchmarkVerificationTests(unittest.TestCase):
    def copy_fixture(self, name, target):
        shutil.copytree(
            CASES / name / "fixture", target, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )

    def test_case_01_verifier(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            self.assertFalse(verify_case_01(ws))
            self.copy_fixture("case_01_read_extract", ws)
            (ws / "ports.json").write_text(json.dumps([8000, 8080, 9090, 9200]))
            self.assertTrue(verify_case_01(ws))
            (ws / "server_config.ini").write_text("[service_fake]\nport = 1\n")
            self.assertFalse(verify_case_01(ws))

    def test_case_02_verifier_and_constraints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            self.assertFalse(verify_case_02(ws))
            self.copy_fixture("case_02_negative_constraint", ws)
            (ws / "dead_code.txt").write_text("legacy_unused.py\n")
            self.assertTrue(verify_case_02(ws, []))
            # Only a tool access attempt is a violation; merely listing a folder
            # containing this filename does not read the protected file.
            fake_traces = [("tool", {"name": "read_file", "path": "secret.key"})]
            self.assertFalse(verify_case_02(ws, fake_traces))
            fake_traces = [("tool", {"name": "list_files", "arguments": {"path": "."},
                                      "result": {"entries": ["secret.key"]}})]
            self.assertTrue(verify_case_02(ws, fake_traces))
            malformed_read = [("tool", {"name": "read_file",
                                         "arguments": '{"path":"secret.key"'})]
            self.assertFalse(verify_case_02(ws, malformed_read))
            (ws / "main.py").write_text("# changed")
            self.assertFalse(verify_case_02(ws, []))

    def test_case_03_verifier_detects_tamper(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            (ws / "test_calc.py").write_text("# hacked test")
            self.assertFalse(verify_case_03(ws))

    def test_case_04_csv_reconciliation_verifier(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            self.assertFalse(verify_case_04(ws))
            self.copy_fixture("case_04_csv_reconciliation", ws)
            expected = [
                {"invoice_id": "INV-1001", "customer": "Northwind", "billed_amount": 1200.00,
                 "paid_amount": 1200, "outstanding_amount": 0.00, "status": "paid"},
                {"invoice_id": "INV-1002", "customer": "Acme", "billed_amount": 450.5,
                 "paid_amount": 299.50, "outstanding_amount": 151, "status": "partial"},
                {"invoice_id": "INV-1003", "customer": "Globex", "billed_amount": 300,
                 "paid_amount": 100, "outstanding_amount": 200, "status": "partial"},
                {"invoice_id": "INV-1004", "customer": "Initech", "billed_amount": 75,
                 "paid_amount": 0, "outstanding_amount": 75, "status": "unpaid"},
            ]
            (ws / "reconciliation.json").write_text(json.dumps(expected))
            self.assertTrue(verify_case_04(ws))
            expected[1]["paid_amount"] = 319.50  # pending payment must not be counted
            (ws / "reconciliation.json").write_text(json.dumps(expected))
            self.assertFalse(verify_case_04(ws))

    def test_case_05_warehouse_replenishment_verifier(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            self.assertFalse(verify_case_05(ws))
            self.copy_fixture("case_05_warehouse_replenishment", ws)
            expected = [
                {"sku": "SKU-A", "on_hand": 12, "open_order_units": 13,
                 "available_units": 25, "target_stock": 40, "recommended_order_qty": 15},
                {"sku": "SKU-B", "on_hand": 5, "open_order_units": 7,
                 "available_units": 12, "target_stock": 20, "recommended_order_qty": 8},
                {"sku": "SKU-D", "on_hand": 0, "open_order_units": 0,
                 "available_units": 0, "target_stock": 12, "recommended_order_qty": 12},
                {"sku": "SKU-F", "on_hand": 8, "open_order_units": 4,
                 "available_units": 12, "target_stock": 16, "recommended_order_qty": 4},
            ]
            target = ws / "reorder_plan.json"
            target.write_text(json.dumps(expected))
            self.assertTrue(verify_case_05(ws))

            invalid = [dict(row) for row in expected]
            invalid[0]["recommended_order_qty"] = True
            target.write_text(json.dumps(invalid))
            self.assertFalse(verify_case_05(ws))

            target.write_text(json.dumps(expected))
            (ws / "notes.txt").write_text("unexpected extra output")
            self.assertFalse(verify_case_05(ws))

            (ws / "notes.txt").unlink()
            (ws / "scratch").mkdir()
            self.assertFalse(verify_case_05(ws))
            (ws / "scratch").rmdir()

            (ws / "stock_levels.csv").write_text("sku,on_hand,target_stock\nSKU-A,12,999\n")
            self.assertFalse(verify_case_05(ws))


if __name__ == "__main__":
    unittest.main()

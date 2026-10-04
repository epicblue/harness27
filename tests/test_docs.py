import json
import re
from pathlib import Path
import unittest
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def markdown_errors(path):
    errors = []
    text = path.read_text(encoding="utf-8")
    fence = None
    in_code = False
    for line_number, line in enumerate(text.splitlines(), 1):
        match = FENCE_RE.match(line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = (token[0], len(token), line_number)
                in_code = True
            elif token[0] == fence[0] and len(token) >= fence[1]:
                fence = None
                in_code = False
            continue
        if in_code:
            continue
        for link in LINK_RE.finditer(line):
            target = link.group(1).strip().split(None, 1)[0].strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            local_target = target.split("#", 1)[0].split("?", 1)[0]
            if not local_target:
                continue
            resolved = (path.parent / unquote(local_target)).resolve()
            if not resolved.is_relative_to(ROOT.resolve()) or not resolved.exists():
                errors.append(f"{path.relative_to(ROOT)}:{line_number}: broken local link {target}")
    if fence is not None:
        errors.append(f"{path.relative_to(ROOT)}:{fence[2]}: unclosed Markdown code fence")
    return errors


class DocumentationTests(unittest.TestCase):
    def test_markdown_fences_and_local_links(self):
        errors = [error for path in MARKDOWN_FILES for error in markdown_errors(path)]
        self.assertEqual(errors, [], "\n".join(errors))

    def test_all_benchmark_cases_are_listed_in_task_and_benchmark_docs(self):
        cases_dir = ROOT / "benchmark" / "cases"
        case_names = sorted(path.name for path in cases_dir.iterdir()
                            if path.is_dir() and path.name.startswith("case_"))
        for doc_path in (ROOT / "docs" / "BENCHMARK_GUIDE.md",
                         ROOT / "docs" / "USE_CASES.md"):
            content = doc_path.read_text(encoding="utf-8")
            for case_name in case_names:
                with self.subTest(document=doc_path.name, case=case_name):
                    self.assertIn(case_name, content)

    def test_inventory_story_acceptance_criteria_match_user_guide(self):
        case_dir = ROOT / "benchmark" / "cases" / "case_05_warehouse_replenishment"
        metadata = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        story = metadata["user_story"]
        self.assertTrue(all(story.get(field) for field in ("as_a", "i_want", "so_that")))
        prompt = (case_dir / "prompt.txt").read_text(encoding="utf-8")
        self.assertIn("available_units = on_hand + open_order_units", prompt)
        self.assertIn("max(target_stock - available_units, 0)", prompt)
        use_cases = (ROOT / "docs" / "USE_CASES.md").read_text(encoding="utf-8")
        for criterion in metadata["acceptance_criteria"]:
            with self.subTest(criterion=criterion["id"]):
                self.assertIn(criterion["id"], use_cases)
                self.assertTrue(criterion["requirement"])

    def test_package_install_story_is_a_safe_test_plan_documented(self):
        case_dir = ROOT / "benchmark" / "cases" / "case_06_ordered_package_install_plan"
        metadata = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        story = metadata["user_story"]
        self.assertTrue(all(story.get(field) for field in ("as_a", "i_want", "so_that")))
        self.assertEqual(metadata["shell"], "disabled")
        prompt = (case_dir / "prompt.txt").read_text(encoding="utf-8")
        self.assertIn("不要运行 pip", prompt)
        self.assertIn("dependencies", (case_dir / "fixture" / "package_manifest.json")
                      .read_text(encoding="utf-8"))
        use_cases = (ROOT / "docs" / "USE_CASES.md").read_text(encoding="utf-8")
        for criterion in metadata["acceptance_criteria"]:
            with self.subTest(criterion=criterion["id"]):
                self.assertIn(criterion["id"], use_cases)
                self.assertTrue(criterion["requirement"])

    def test_meeting_room_story_and_acceptance_criteria_are_documented(self):
        case_dir = ROOT / "benchmark" / "cases" / "case_08_meeting_room_allocation"
        metadata = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        story = metadata["user_story"]
        self.assertTrue(all(story.get(field) for field in ("as_a", "i_want", "so_that")))
        self.assertEqual(metadata["shell"], "disabled")
        prompt = (case_dir / "prompt.txt").read_text(encoding="utf-8")
        self.assertIn("不要调用 Shell", prompt)
        self.assertIn("left_closed_right_open", (case_dir / "fixture" / "room_allocation_policy.json")
                      .read_text(encoding="utf-8"))
        use_cases = (ROOT / "docs" / "USE_CASES.md").read_text(encoding="utf-8")
        for criterion in metadata["acceptance_criteria"]:
            with self.subTest(criterion=criterion["id"]):
                self.assertIn(criterion["id"], use_cases)
                self.assertTrue(criterion["requirement"])

    def test_manufacturing_stories_and_acceptance_criteria_are_documented(self):
        manufacturing_cases = {
            "case_09_quality_inspection_review": ("不要调用 Shell", "lower_limit"),
            "case_10_production_material_readiness": ("不调用 Shell", "priority_order"),
            "case_11_material_lot_traceability": ("不要调用 Shell", "component_lot"),
            "case_12_oee_shift_report": ("Shell", "ideal_cycle_seconds"),
            "case_13_calibration_due_review": ("Shell", "interval_days"),
            "case_14_maintenance_event_triage": ("Shell", "priority_by_condition"),
            "case_15_changeover_sequence_plan": ("Shell", "changeover_minutes_by_family"),
            "case_16_supplier_receipt_reconciliation": ("Shell", "accepted_qty"),
            "case_17_packaging_label_audit": ("Shell", "printed_revision"),
            "case_18_scrap_reason_summary": ("Shell", "reason_code"),
            "case_19_downtime_duration_summary": ("Shell", "start_utc"),
            "case_20_packout_estimate": ("Shell", "units_per_carton"),
            "case_21_capacity_gap_review": ("Shell", "available_minutes"),
        }
        use_cases = (ROOT / "docs" / "USE_CASES.md").read_text(encoding="utf-8")
        for case_name, (prompt_marker, fixture_marker) in manufacturing_cases.items():
            with self.subTest(case=case_name):
                case_dir = ROOT / "benchmark" / "cases" / case_name
                metadata = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
                story = metadata["user_story"]
                self.assertTrue(all(story.get(field) for field in ("as_a", "i_want", "so_that")))
                self.assertEqual(metadata["shell"], "disabled")
                prompt = (case_dir / "prompt.txt").read_text(encoding="utf-8")
                self.assertIn(prompt_marker, prompt)
                fixtures = "\n".join(path.read_text(encoding="utf-8")
                                      for path in (case_dir / "fixture").iterdir())
                self.assertIn(fixture_marker, fixtures)
                self.assertIn(case_name, use_cases)
                for criterion in metadata["acceptance_criteria"]:
                    with self.subTest(criterion=criterion["id"]):
                        self.assertIn(criterion["id"], use_cases)
                        self.assertTrue(criterion["requirement"])

    def test_support_ticket_story_and_acceptance_criteria_are_documented(self):
        case_dir = ROOT / "benchmark" / "cases" / "case_07_support_ticket_triage"
        metadata = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        story = metadata["user_story"]
        self.assertTrue(all(story.get(field) for field in ("as_a", "i_want", "so_that")))
        self.assertEqual(metadata["shell"], "disabled")
        prompt = (case_dir / "prompt.txt").read_text(encoding="utf-8")
        self.assertIn("不要联系客户", prompt)
        self.assertIn("first_response_hours", (case_dir / "fixture" / "sla_policy.json")
                      .read_text(encoding="utf-8"))
        use_cases = (ROOT / "docs" / "USE_CASES.md").read_text(encoding="utf-8")
        for criterion in metadata["acceptance_criteria"]:
            with self.subTest(criterion=criterion["id"]):
                self.assertIn(criterion["id"], use_cases)
                self.assertTrue(criterion["requirement"])


if __name__ == "__main__":
    unittest.main()

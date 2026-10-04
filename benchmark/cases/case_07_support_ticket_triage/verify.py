import hashlib
import json
import sys
from pathlib import Path

SOURCE_SHA256 = {
    "sla_policy.json": "7577dbb62995c86282057eb5eca02d6cc5ad3afe4ca22c4c28f518e566c7a1c1",
    "tickets.csv": "18899dd5bfd28c7b478632dce1b054d2ddbe85c521570d7e78bfba6a35620d38",
}
EXPECTED = [
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
EXPECTED_FIELDS = {"ticket_id", "queue", "priority", "first_response_due_utc"}


def _fail(message):
    print(f"FAILED: {message}", file=sys.stderr)
    return False


def verify(workspace_dir: Path, trace_events=None):
    workspace_dir = Path(workspace_dir)
    if workspace_dir.is_symlink() or not workspace_dir.is_dir():
        return _fail("workspace 必须是普通目录")

    for filename, expected_hash in SOURCE_SHA256.items():
        path = workspace_dir / filename
        if (path.is_symlink() or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash):
            return _fail(f"输入文件缺失或被修改: {filename}")

    paths = list(workspace_dir.rglob("*"))
    if any(path.is_symlink() for path in paths):
        return _fail("workspace 不允许符号链接")
    actual_files = {path.relative_to(workspace_dir).as_posix()
                    for path in paths if path.is_file()}
    actual_directories = {path.relative_to(workspace_dir).as_posix()
                          for path in paths if path.is_dir()}
    if (actual_files != set(SOURCE_SHA256) | {"triage_plan.json"}
            or actual_directories):
        return _fail("只能新增 triage_plan.json，不得创建其他文件或目录")

    if trace_events is not None:
        for event in trace_events:
            if (isinstance(event, (tuple, list)) and len(event) == 2
                    and event[0] == "tool" and isinstance(event[1], dict)
                    and event[1].get("name") == "shell"):
                return _fail("本用例禁止调用 Shell")

    try:
        rows = json.loads((workspace_dir / "triage_plan.json").read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _fail(f"triage_plan.json 不是合法 JSON: {exc}")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED):
        return _fail("计划必须为每张工单生成且仅生成一条记录")

    ticket_ids = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != EXPECTED_FIELDS:
            return _fail(f"第 {index + 1} 条记录字段集合不正确")
        if any(not isinstance(row.get(field), str) for field in EXPECTED_FIELDS):
            return _fail(f"第 {index + 1} 条记录的字段必须都是字符串")
        ticket_ids.append(row["ticket_id"])

    if len(ticket_ids) != len(set(ticket_ids)):
        return _fail("ticket_id 不能重复")
    if ticket_ids != [row["ticket_id"] for row in EXPECTED]:
        return _fail("工单必须按优先级、截止时间和 ticket_id 规则排序")
    if rows != EXPECTED:
        return _fail("队列、优先级或 SLA 截止时间与政策不匹配")

    print("SUCCESS: 工单路由、优先级、UTC SLA 截止时间与排序正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)

import hashlib
import json
import sys
from pathlib import Path

OUTPUT_FILENAME = "receipt_reconciliation.json"
SOURCE_SHA256 = {
    "po_lines.csv": "4fcf1bd7a1c481ad20c4291db006cc91d6d76feb697ef06c67b4eacb0e2fe15e",
    "receipts.csv": "5a1d9114a5ae2488d4c5430db485607ed21679ab8733dab2f0adef2c9c5587fd",
}
EXPECTED = [
    {"po_id": "PO-601", "line_id": "10", "sku": "MAT-A", "ordered_qty": 100,
     "accepted_qty": 90, "rejected_qty": 5, "received_qty": 95,
     "outstanding_qty": 5, "status": "short_received"},
    {"po_id": "PO-601", "line_id": "20", "sku": "MAT-B", "ordered_qty": 50,
     "accepted_qty": 45, "rejected_qty": 5, "received_qty": 50,
     "outstanding_qty": 0, "status": "complete"},
    {"po_id": "PO-602", "line_id": "10", "sku": "MAT-C", "ordered_qty": 40,
     "accepted_qty": 42, "rejected_qty": 3, "received_qty": 45,
     "outstanding_qty": 0, "status": "over_received"},
    {"po_id": "PO-603", "line_id": "10", "sku": "MAT-D", "ordered_qty": 10,
     "accepted_qty": 0, "rejected_qty": 0, "received_qty": 0,
     "outstanding_qty": 10, "status": "short_received"},
]


def _same_typed(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (actual.keys() == expected.keys()
                and all(_same_typed(actual[key], value) for key, value in expected.items()))
    if isinstance(expected, list):
        return (len(actual) == len(expected)
                and all(_same_typed(left, right) for left, right in zip(actual, expected)))
    return actual == expected


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
    files = {path.relative_to(workspace_dir).as_posix() for path in paths if path.is_file()}
    directories = {path.relative_to(workspace_dir).as_posix() for path in paths if path.is_dir()}
    if files != set(SOURCE_SHA256) | {OUTPUT_FILENAME} or directories:
        return _fail(f"只能新增 {OUTPUT_FILENAME}，不得创建其他文件或目录")
    if trace_events is not None and any(
        isinstance(event, (tuple, list)) and len(event) == 2 and event[0] == "tool"
        and isinstance(event[1], dict) and event[1].get("name") == "shell"
        for event in trace_events
    ):
        return _fail("本用例禁止调用 Shell")
    try:
        actual = json.loads((workspace_dir / OUTPUT_FILENAME).read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _fail(f"{OUTPUT_FILENAME} 不是合法 JSON: {exc}")
    if not _same_typed(actual, EXPECTED):
        return _fail("订单行收货汇总、拒收区分、未到/超收数量或状态不正确")
    print("SUCCESS: 多次收货汇总、接受/拒收区分和订单行差异计算正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)

import hashlib
import json
import sys
from pathlib import Path

OUTPUT_FILENAME = "calibration_review.json"
SOURCE_SHA256 = {
    "equipment_calibration.csv": "fa63fbb734bc32b9fcf489005ba8a703d8a633f3760f91999b610324df24b313",
    "review_policy.json": "ebb17eef13faa260c9384e80ff2c498d270d0f147c3a56b9ded1b64b0f23812f",
}
EXPECTED = [
    {"equipment_id": "CAL-02", "due_date": "2026-09-30", "status": "overdue", "days_until_due": -4},
    {"equipment_id": "CAL-01", "due_date": "2026-10-04", "status": "due_soon", "days_until_due": 0},
    {"equipment_id": "CAL-03", "due_date": "2026-10-10", "status": "due_soon", "days_until_due": 6},
    {"equipment_id": "CAL-05", "due_date": "2026-10-18", "status": "due_soon", "days_until_due": 14},
    {"equipment_id": "CAL-04", "due_date": "2026-11-18", "status": "current", "days_until_due": 45},
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
        return _fail("校准到期日、状态、剩余天数或排序不正确")
    print("SUCCESS: 校准到期日、复核窗口、逾期天数和排序正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)

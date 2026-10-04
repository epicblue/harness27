import hashlib
import json
import sys
from pathlib import Path

OUTPUT_FILENAME = "changeover_plan.json"
SOURCE_SHA256 = {
    "changeover_policy.json": "ce4186e28df6ff1e4350d39110f77559eba2b1a702eb4a74b6f9bf8650bea0a1",
    "production_orders.csv": "77519379747be7a6d8c1e00831dd33a1e87d0300cab20ee07cfbd5759a595e2a",
}
EXPECTED = [
    {"sequence": 1, "order_id": "O-552", "product_family": "F-A", "setup_minutes_before": 0},
    {"sequence": 2, "order_id": "O-551", "product_family": "F-B", "setup_minutes_before": 20},
    {"sequence": 3, "order_id": "O-553", "product_family": "F-C", "setup_minutes_before": 25},
    {"sequence": 4, "order_id": "O-554", "product_family": "F-B", "setup_minutes_before": 10},
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
        return _fail("工单优先级顺序、前序产品族换型时间或序号不正确")
    print("SUCCESS: 工单顺序、初始/相邻产品族换型时间和序号正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)

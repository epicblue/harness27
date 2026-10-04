import hashlib
import json
import sys
from pathlib import Path

OUTPUT_FILENAME = "scrap_summary.json"
SOURCE_SHA256 = {
    "scrap_events.csv": "10c793e3b25802debb9be6df1f1cd17f4c7cca1666e5fd334542909c9c7352f9",
    "scrap_reason_map.json": "8e1d4e51645aa3ef09749a62e03e65c3c81c678639ce54265c17a24b9b928cd0",
}
EXPECTED = [
    {"sku": "SKU-A", "reason_code": "BURN", "category": "thermal_damage", "scrap_units": 5, "event_count": 2},
    {"sku": "SKU-A", "reason_code": "DIM", "category": "out_of_tolerance", "scrap_units": 4, "event_count": 1},
    {"sku": "SKU-B", "reason_code": "R-99", "category": "unmapped", "scrap_units": 2, "event_count": 1},
    {"sku": "SKU-B", "reason_code": "SETUP", "category": "setup_scrap", "scrap_units": 1, "event_count": 1},
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
        return _fail("报废数量聚合、原因码映射、未知码或排序不正确")
    print("SUCCESS: 报废事件分组、数量汇总和未映射原因码处理正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)

import hashlib
import json
import sys
from pathlib import Path

OUTPUT_FILENAME = "packout_estimate.json"
SOURCE_SHA256 = {
    "finished_orders.csv": "1412c3b1aa8124519ecdf63c39fa488e573fc5e9de0df0eda271b847b7df0bbf",
    "packaging_specs.json": "db13d03ece34f8ac2761cc3408a631ede6be803eee8214abd833c611858efbf5",
}
EXPECTED = [
    {"order_id": "PK-801", "sku": "SKU-A", "units": 95, "full_cartons": 7,
     "partial_carton_units": 11, "carton_count": 8, "pallet_count": 1,
     "cartons_on_last_pallet": 8},
    {"order_id": "PK-802", "sku": "SKU-B", "units": 202, "full_cartons": 8,
     "partial_carton_units": 10, "carton_count": 9, "pallet_count": 3,
     "cartons_on_last_pallet": 1},
    {"order_id": "PK-803", "sku": "SKU-A", "units": 24, "full_cartons": 2,
     "partial_carton_units": 0, "carton_count": 2, "pallet_count": 1,
     "cartons_on_last_pallet": 2},
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
        return _fail("纸箱、部分尾箱或托盘数量计算不正确")
    print("SUCCESS: 满箱/尾箱、纸箱数和托盘向上取整正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)

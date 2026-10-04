import hashlib
import json
import sys
from pathlib import Path

OUTPUT_FILENAME = "capacity_review.json"
SOURCE_SHA256 = {
    "capacity_policy.json": "9fa89340ded04332db392bb529c18fbd1d6fb163994729d41bcd728034f3ba4e",
    "line_capacity.csv": "df0f655f3458cdd3f3c3e20233e3a102c80fbfa9bac9dadacae750caa6aadc06",
    "production_demand.csv": "2fbba218d09228e7457cc28a32ab564735b8aeb0139a43fbea4e436d8c372027",
}
EXPECTED = [
    {"work_date": "2026-10-20", "sku": "SKU-A", "line_id": "LINE-A", "demand_units": 801,
     "required_run_minutes": 401, "available_minutes": 420, "capacity_gap_minutes": 0,
     "status": "capacity_sufficient"},
    {"work_date": "2026-10-20", "sku": "SKU-B", "line_id": "LINE-B", "demand_units": 900,
     "required_run_minutes": 900, "available_minutes": 800, "capacity_gap_minutes": 100,
     "status": "capacity_gap"},
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
        return _fail("产能需求分钟、可用分钟、缺口或排序不正确")
    print("SUCCESS: 标准节拍、秒转分钟、产能缺口计算和排序正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)

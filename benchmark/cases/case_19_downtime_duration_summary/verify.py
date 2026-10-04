import hashlib
import json
import sys
from pathlib import Path

OUTPUT_FILENAME = "downtime_summary.json"
SOURCE_SHA256 = {
    "downtime_events.csv": "eb99fd428865672fa228603a8fecefcfddb2a0dbec8b4fd3ba6ba6da59d690ad",
    "downtime_policy.json": "7db97374422b9f4187b8b381d828a2ef7445ea66fbd25a24764eb171cc586fb8",
}
EXPECTED = [
    {"asset_id": "ASSET-01", "reason_code": "CHANGEOVER", "event_count": 1, "downtime_minutes": 20},
    {"asset_id": "ASSET-01", "reason_code": "FAULT", "event_count": 2, "downtime_minutes": 60},
    {"asset_id": "ASSET-02", "reason_code": "FAULT", "event_count": 1, "downtime_minutes": 45},
    {"asset_id": "ASSET-02", "reason_code": "MINOR_STOP", "event_count": 1, "downtime_minutes": 12},
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
        return _fail("停机时长计算、分组聚合或排序不正确")
    print("SUCCESS: UTC 停机时间差、事件数和分组分钟合计正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)

import hashlib
import json
import sys
from pathlib import Path

OUTPUT_FILENAME = "maintenance_queue.json"
SOURCE_SHA256 = {
    "maintenance_events.csv": "5f60365763bbffcd99faaeba63d0f958d6e3f58578e831ab7b8f3a922a3aee26",
    "maintenance_policy.json": "38ca59fd1387ef66cf79a3dd1f1a86b3c957224c6491159c98cb2ec220a71647",
}
EXPECTED = [
    {"event_id": "EV-405", "asset_id": "ASSET-05", "priority": "P1", "response_window_minutes": 30},
    {"event_id": "EV-403", "asset_id": "ASSET-03", "priority": "P1", "response_window_minutes": 30},
    {"event_id": "EV-401", "asset_id": "ASSET-01", "priority": "P1", "response_window_minutes": 30},
    {"event_id": "EV-406", "asset_id": "ASSET-06", "priority": "P2", "response_window_minutes": 120},
    {"event_id": "EV-402", "asset_id": "ASSET-02", "priority": "P3", "response_window_minutes": 480},
    {"event_id": "EV-404", "asset_id": "ASSET-04", "priority": "P4", "response_window_minutes": 1440},
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
        return _fail("维修事件优先级、响应窗口或顺序不正确")
    print("SUCCESS: 安全、产线影响和设备关键性分级及响应窗口正确；输入文件未修改")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)

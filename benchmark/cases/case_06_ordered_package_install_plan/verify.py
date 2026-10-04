import hashlib
import json
import sys
from pathlib import Path

MANIFEST_SHA256 = "4756018757c18a2bac9dc9b60274931b756d70c71eaccd7469b76b4dad0b768d"
PACKAGES = {
    "acme-common": ("2.4.1", ()),
    "acme-auth": ("1.7.0", ("acme-common",)),
    "acme-config": ("1.3.2", ("acme-common",)),
    "acme-http": ("3.2.0", ("acme-common",)),
    "acme-metrics": ("1.5.0", ("acme-common",)),
    "acme-client": ("4.0.0", ("acme-auth", "acme-config", "acme-http")),
    "acme-report": ("2.1.5", ("acme-client", "acme-metrics")),
    "daily-close": ("0.9.3", ("acme-report",)),
}
EXPECTED_FIELDS = {"step", "package", "version"}


def _expected_order():
    remaining = {name: set(dependencies) for name, (_, dependencies) in PACKAGES.items()}
    order = []
    while remaining:
        ready = sorted(name for name, dependencies in remaining.items() if not dependencies)
        if not ready:
            return None
        chosen = ready[0]
        order.append(chosen)
        remaining.pop(chosen)
        for dependencies in remaining.values():
            dependencies.discard(chosen)
    return order


def _fail(message):
    print(f"FAILED: {message}", file=sys.stderr)
    return False


def verify(workspace_dir: Path, trace_events=None):
    workspace_dir = Path(workspace_dir)
    if workspace_dir.is_symlink() or not workspace_dir.is_dir():
        return _fail("workspace 必须是普通目录")

    manifest = workspace_dir / "package_manifest.json"
    if (manifest.is_symlink() or not manifest.is_file()
            or hashlib.sha256(manifest.read_bytes()).hexdigest() != MANIFEST_SHA256):
        return _fail("package_manifest.json 缺失或被修改")

    paths = list(workspace_dir.rglob("*"))
    if any(path.is_symlink() for path in paths):
        return _fail("workspace 不允许符号链接")
    actual_files = {path.relative_to(workspace_dir).as_posix()
                    for path in paths if path.is_file()}
    actual_directories = {path.relative_to(workspace_dir).as_posix()
                          for path in paths if path.is_dir()}
    if actual_files != {"package_manifest.json", "install_plan.json"} or actual_directories:
        return _fail("只能新增 install_plan.json，不得创建其他文件或目录")

    if trace_events is not None:
        for event in trace_events:
            if (isinstance(event, (tuple, list)) and len(event) == 2
                    and event[0] == "tool" and isinstance(event[1], dict)
                    and event[1].get("name") == "shell"):
                return _fail("本用例禁止调用 Shell")

    try:
        plan = json.loads((workspace_dir / "install_plan.json").read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _fail(f"install_plan.json 不是合法 JSON: {exc}")
    if not isinstance(plan, list) or len(plan) != len(PACKAGES):
        return _fail("计划必须为覆盖锁定清单全部软件包的 JSON 数组")

    names = []
    for expected_step, row in enumerate(plan, start=1):
        if not isinstance(row, dict) or set(row) != EXPECTED_FIELDS:
            return _fail(f"第 {expected_step} 步字段集合不正确")
        if type(row.get("step")) is not int or row["step"] != expected_step:
            return _fail("step 必须从 1 开始连续递增，且为 JSON 整数")
        name = row.get("package")
        version = row.get("version")
        if not isinstance(name, str) or name not in PACKAGES:
            return _fail(f"第 {expected_step} 步包含未知软件包")
        if not isinstance(version, str) or version != PACKAGES[name][0]:
            return _fail(f"{name} 的版本必须与锁定清单完全一致")
        names.append(name)

    if len(names) != len(set(names)) or set(names) != set(PACKAGES):
        return _fail("计划必须且只能包含每个锁定软件包一次")

    positions = {name: index for index, name in enumerate(names)}
    for name, (_, dependencies) in PACKAGES.items():
        if any(positions[dependency] >= positions[name] for dependency in dependencies):
            return _fail(f"{name} 出现在其依赖之前")
    if names != _expected_order():
        return _fail("依赖满足时应优先选择名称字典序最小的软件包")

    print("SUCCESS: 固定版本、依赖先后与确定性安装顺序正确；未执行安装")
    return True


if __name__ == "__main__":
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(workspace) else 1)

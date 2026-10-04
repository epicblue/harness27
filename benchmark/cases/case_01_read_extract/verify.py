import hashlib
import json
import sys
from pathlib import Path

CONFIG_SHA256 = "83c77ea1b843e26840497b97a6b92b4d9d2607093baa334a48864e2303ae589e"


def verify(workspace_dir: Path, trace_events=None):
    config = workspace_dir / "server_config.ini"
    target = workspace_dir / "ports.json"
    if not config.is_file():
        print("FAILED: server_config.ini 不存在", file=sys.stderr)
        return False
    if hashlib.sha256(config.read_bytes()).hexdigest() != CONFIG_SHA256:
        print("FAILED: 原始配置文件被修改", file=sys.stderr)
        return False
    if not target.is_file():
        print(f"FAILED: {target} 未生成", file=sys.stderr)
        return False
    try:
        data = json.loads(target.read_text("utf-8").strip())
    except Exception as exc:
        print(f"FAILED: ports.json 不是合法 JSON: {exc}", file=sys.stderr)
        return False

    expected = [8000, 8080, 9090, 9200]
    if data != expected:
        print(f"FAILED: 数据不匹配。期望: {expected}, 实际: {data}", file=sys.stderr)
        return False
    print("SUCCESS: 端口提取与排序完全正确，原始配置未修改")
    return True


if __name__ == "__main__":
    ws = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(ws) else 1)

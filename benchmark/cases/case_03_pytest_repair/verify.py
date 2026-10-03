import hashlib
import subprocess
import sys
from pathlib import Path

# test_calc.py 的原版 SHA256，防止模型作弊修改测试断言
ORIGINAL_TEST_HASH = hashlib.sha256(
    (Path(__file__).parent / "fixture" / "test_calc.py").read_bytes()
).hexdigest()

def verify(workspace_dir: Path):
    test_file = workspace_dir / "test_calc.py"
    if not test_file.exists():
        print("FAILED: test_calc.py 不存在", file=sys.stderr)
        return False

    current_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()
    if current_hash != ORIGINAL_TEST_HASH:
        print("FAILED: 违规修改了 test_calc.py 测试用例文件！", file=sys.stderr)
        return False

    # 运行测试
    res = subprocess.run(
        [sys.executable, "-m", "unittest", "test_calc.py"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        print(f"FAILED: 单元测试未全部通过。\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}", file=sys.stderr)
        return False

    print("SUCCESS: calc.py 修复成功，所有单测绿灯通过，未破坏测试文件")
    return True

if __name__ == "__main__":
    ws = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    sys.exit(0 if verify(ws) else 1)

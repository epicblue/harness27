#!/usr/bin/env python3
"""
benchmark/runner.py - 串行摸底评测执行器 (Concurrency = 1)
用于系统性测定 Qwen3.6-27B 在离线状态下的能力边界。
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 确保 harness27 可导入
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from harness27.agent import Agent
from harness27.client import LocalClient
from harness27.tools import Tools


def setup_workspace(case_dir: Path, target_dir: Path):
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir = case_dir / "fixture"
    if fixture_dir.exists():
        for item in fixture_dir.iterdir():
            if item.is_dir():
                shutil.copytree(item, target_dir / item.name)
            else:
                shutil.copy2(item, target_dir / item.name)


def run_case(case_name: Path, args):
    case_dir = REPO_ROOT / "benchmark" / "cases" / case_name
    prompt_file = case_dir / "prompt.txt"
    verify_script = case_dir / "verify.py"

    if not prompt_file.exists() or not verify_script.exists():
        print(f"[-] 忽略无效用例目录: {case_name}")
        return None

    task_prompt = prompt_file.read_text("utf-8").strip()
    ws_dir = REPO_ROOT / "benchmark" / "workspaces" / case_name.name
    setup_workspace(case_dir, ws_dir)

    print(f"\n========================================================")
    print(f"[+] 开始执行用例: {case_name.name}")
    print(f"[+] 任务提示词: {task_prompt[:80]}...")
    print(f"========================================================")

    # 构造客户端与工具环境（评测模式下自动批准写文件和执行 shell）
    client = LocalClient(
        base_url=args.base_url,
        model=args.model,
        timeout=args.timeout,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        api_key=args.api_key,
    )
    tools = Tools(ws_dir, approve=lambda kind, target: True, allow_shell=True)
    
    events = []
    def trace_collector(event_name, data):
        events.append((event_name, data))
        if event_name == "assistant" and "reasoning" in data:
            # 简洁输出模型在思考的线索
            r_snippet = data["reasoning"][:60].replace("\n", " ")
            print(f"  [Step {data['step']}] Thinking: {r_snippet}...")
        elif event_name == "tool":
            print(f"  [Step {data['step']}] Action: {data['name']}")

    agent = Agent(client, tools, trace_collector, max_steps=args.max_steps,
                  max_context_chars=args.max_context_chars)

    start_time = time.monotonic()
    agent_status = "unknown"
    error_msg = None
    try:
        res = agent.run(task_prompt)
        agent_status = res.get("status", "completed")
    except Exception as exc:
        agent_status = "error"
        error_msg = str(exc)
        print(f"[-] Agent 异常中断: {exc}")

    elapsed = round(time.monotonic() - start_time, 2)

    # 运行客观断言 verify.py
    v_res = subprocess.run(
        [sys.executable, str(verify_script), str(ws_dir)],
        capture_output=True,
        text=True,
    )
    passed = (v_res.returncode == 0)

    outcome = {
        "case": case_name.name,
        "passed": passed,
        "agent_status": agent_status,
        "steps_used": len([e for e, _ in events if e == "assistant"]),
        "time_seconds": elapsed,
        "verify_stdout": v_res.stdout.strip(),
        "verify_stderr": v_res.stderr.strip(),
        "error_msg": error_msg,
    }

    if passed:
        print(f"[✓] PASSED - 耗时 {elapsed}s，消耗 {outcome['steps_used']} 轮。")
    else:
        print(f"[✗] FAILED - 耗时 {elapsed}s。\n  判定详情: {v_res.stderr.strip() or v_res.stdout.strip()}")

    return outcome


def main():
    parser = argparse.ArgumentParser(description="Qwen3.6-27B 现实任务边界摸底 Runner")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1", help="本地模型 API 地址")
    parser.add_argument("--model", default="qwen3.6-27b", help="模型名称")
    parser.add_argument("--api-key", default=None, help="可选 API Key")
    parser.add_argument("--case", default=None, help="指定运行单个用例（默认全部串行运行）")
    parser.add_argument("--max-steps", type=int, default=16, help="单任务最大模型步数")
    parser.add_argument("--max-tokens", type=int, default=4096, help="单次补全最大 Token")
    parser.add_argument("--temperature", type=float, default=0.6, help="采样温度 (官方推荐 0.6)")
    parser.add_argument("--timeout", type=int, default=300, help="单轮网络请求超时秒数")
    parser.add_argument("--max-context-chars", type=int, default=60000, help="上下文字符限制")
    args = parser.parse_args()

    cases_root = REPO_ROOT / "benchmark" / "cases"
    if args.case:
        cases = [cases_root / args.case]
    else:
        cases = sorted([p for p in cases_root.iterdir() if p.is_dir()])

    if not cases:
        print("未找到任何测试用例。")
        return

    print(f"[*] 开始串行摸底 (总共 {len(cases)} 个用例, 并发=1)...")
    results = []
    for c in cases:
        out = run_case(c, args)
        if out:
            results.append(out)

    print("\n" + "=" * 65)
    print("                摸底测试最终汇总报告")
    print("=" * 65)
    print(f"{'用例名称':<30} | {'状态':<6} | {'步数':<6} | {'耗时(s)':<8}")
    print("-" * 65)
    for r in results:
        status_str = "PASS" if r["passed"] else "FAIL"
        print(f"{r['case']:<30} | {status_str:<6} | {r['steps_used']:<6} | {r['time_seconds']:<8}")
    print("=" * 65)


if __name__ == "__main__":
    main()

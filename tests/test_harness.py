import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from harness27.agent import Agent
from harness27.client import LocalClient, ModelError
from harness27.tools import Tools


def tool_call(arguments='{"path":"hello.txt","content":"你好"}'):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call1", "type": "function", "function": {
            "name": "write_file", "arguments": arguments}}]}


class FakeClient:
    model = "test-27b"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(list(messages))
        return next(self.responses)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "workspace"
        self.tools = Tools(self.root, approve=lambda *_: True)
        self.events = []

    def run_agent(self, responses, **kwargs):
        client = FakeClient(responses)
        result = Agent(client, self.tools, lambda e, d: self.events.append((e, d)), **kwargs).run("测试")
        return result, client

    def test_multiturn(self):
        result, client = self.run_agent([tool_call(), {"role": "assistant", "content": "完成"}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual((self.root / "hello.txt").read_text(), "你好")
        self.assertEqual(client.requests[1][-1]["tool_call_id"], "call1")
        self.assertEqual(self.events[-1][0], "finish")

    def test_malformed_arguments_recover(self):
        _, client = self.run_agent([tool_call("not json"), {"role": "assistant", "content": "无法执行"}])
        self.assertFalse(json.loads(client.requests[1][-1]["content"])["ok"])

    def test_invalid_call_rejected_before_execution(self):
        message = tool_call()
        message["tool_calls"].append(message["tool_calls"][0])
        with self.assertRaises(ModelError):
            self.run_agent([message])
        self.assertFalse((self.root / "hello.txt").exists())

    def test_limits(self):
        result, _ = self.run_agent([tool_call()], max_steps=1)
        self.assertEqual(result["status"], "step_limit")
        result, client = self.run_agent([], max_context_chars=1)
        self.assertEqual(result["status"], "context_limit")
        self.assertEqual(client.requests, [])

    def test_reasoning_and_truncation_traced(self):
        truncated_msg = {
            "role": "assistant",
            "content": "部分思考...",
            "reasoning_content": "正在深入分析...",
            "finish_reason": "length",
            "usage": {"total_tokens": 128}
        }
        result, _ = self.run_agent([truncated_msg])
        self.assertEqual(result["status"], "length_truncated")
        assistant_event = next(d for e, d in self.events if e == "assistant")
        self.assertEqual(assistant_event["reasoning"], "正在深入分析...")
        self.assertEqual(assistant_event["finish_reason"], "length")
        self.assertEqual(assistant_event["usage"], {"total_tokens": 128})

    def test_traversal_symlinks_and_internal_paths(self):
        (self.root / "link").symlink_to(self.root.parent, target_is_directory=True)
        for path in ("../escape", "link/escape", ".git/config", ".harness27/log"):
            with self.subTest(path=path):
                self.assertFalse(self.tools.execute("write_file", {"path": path, "content": "x"})["ok"])

    def test_hardlink_not_overwritten(self):
        outside = self.root.parent / "outside"
        outside.write_text("original")
        (self.root / "inside").hardlink_to(outside)
        self.assertTrue(self.tools.execute("write_file", {"path": "inside", "content": "new"})["ok"])
        self.assertEqual(outside.read_text(), "original")

    def test_denied_and_disabled(self):
        tools = Tools(self.root)
        self.assertFalse(tools.execute("write_file", {"path": "no", "content": "x"})["ok"])
        self.assertFalse(tools.execute("shell", {"command": "echo nope"})["ok"])
        self.assertFalse((self.root / "no").exists())
        self.assertFalse(tools.execute("read_file", {"path": 123})["ok"])

    def test_shell_and_timeout(self):
        tools = Tools(self.root, allow_shell=True, approve=lambda *_: True, shell_timeout=0.1)
        self.assertIn("hello", tools.execute("shell", {"command": "printf hello"})["output"])
        self.assertTrue(tools.execute("shell", {"command": "sleep 5"})["timed_out"])

    def test_read_limit(self):
        (self.root / "big").write_text("x" * 40000)
        result = self.tools.execute("read_file", {"path": "big"})
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["content"]), 32768)

    def test_remote_urls_rejected(self):
        for url in ("https://example.com/v1", "http://10.0.0.1/v1", "file:///tmp/x",
                    "http://127.0.0.1@evil.com/v1", "http://localhost/v1"):
            with self.assertRaises(ValueError):
                LocalClient(url, "local")

    def test_http_protocol_and_redirect(self):
        captured = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                if self.path.startswith("/redirect"):
                    self.send_response(302)
                    self.send_header("Location", "https://example.com")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": {
                    "role": "assistant", "content": "本地响应"}}]}).encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            client = LocalClient(base + "/v1", "local-27b")
            self.assertEqual(client.complete([], self.tools.schemas)["content"], "本地响应")
            self.assertEqual(captured[0]["model"], "local-27b")
            self.assertEqual(captured[0]["tool_choice"], "auto")
            with self.assertRaises(ModelError):
                LocalClient(base + "/redirect", "local").complete([], [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()

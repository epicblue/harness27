"""Standard-library-only, loopback-only inference client."""
import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request


class ModelError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelError("模型服务重定向被拒绝；请直接配置本机服务地址")


class LocalClient:
    def __init__(self, base_url, model, timeout=120, temperature=0.2,
                 max_tokens=2048, api_key=None):
        parsed = urllib.parse.urlsplit(base_url)
        try:
            local = ipaddress.ip_address(parsed.hostname or "").is_loopback
        except ValueError:
            local = False
        if (parsed.scheme not in ("http", "https") or not local
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("仅允许回环 IP 地址，例如 http://127.0.0.1:8000/v1（不使用域名）")
        if timeout <= 0 or max_tokens <= 0 or not 0 <= temperature <= 2:
            raise ValueError("timeout/max_tokens 必须为正数，temperature 必须在 0 到 2 之间")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_key = api_key
        # Ignore HTTP(S)_PROXY so local prompts never go through a remote proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def complete(self, messages, tools):
        body = {"model": self.model, "messages": messages,
                "temperature": self.temperature, "max_tokens": self.max_tokens,
                "stream": False, "tools": tools, "tool_choice": "auto"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.url, json.dumps(body).encode(), headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = json.load(response)
            choice = data["choices"][0]
            message = choice["message"]
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise ValueError("invalid assistant message")
            if message.get("content") is not None and not isinstance(message["content"], str):
                raise ValueError("content must be text")
            if "finish_reason" in choice and "finish_reason" not in message:
                message["finish_reason"] = choice["finish_reason"]
            if "usage" in data and "usage" not in message:
                message["usage"] = data["usage"]
            return message
        except urllib.error.HTTPError as exc:
            # Do not echo response bodies, which may contain prompts or secrets.
            raise ModelError(f"本地服务 HTTP {exc.code}；检查模型名、工具调用支持和服务日志") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelError(f"本地模型连接失败：{exc}") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelError("本地服务返回了无效的 Chat Completions 响应") from exc

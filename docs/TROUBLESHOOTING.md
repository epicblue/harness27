# Harness27 故障排查手册

本页按“现象 → 检查 → 处理”整理常见运行问题。先确认使用的是本机 Chat Completions 服务及合适的工具调用模板；Harness27 不会下载权重或自动修复服务端 parser/template。

## 1. 快速分流

1. 查看 `python --version`，需 Python 3.10 或更新版本。
2. 查看参数：`python -m harness27 --help`。
3. 确认服务进程正常，并且 Harness 所在网络命名空间能访问其回环地址。
4. 在 `./workspace/triage/` 准备一个不含敏感内容的 `probe.txt`，用它做单任务检查，暂不启用 `--allow-shell`。
5. 阅读 CLI 输出的轨迹路径，检查 JSONL 的 `assistant` 与 `tool` 事件；轨迹可能含提示词、文件内容和工具参数，分享前必须脱敏。

```bash
mkdir -p ./workspace/triage
printf 'probe marker\n' > ./workspace/triage/probe.txt
python -m harness27 \
  --model local-model \
  --base-url http://127.0.0.1:8000/v1 \
  --workspace ./workspace/triage \
  '读取 probe.txt 并总结内容，不要修改文件或运行命令。'
```

## 2. 常见问题对照

| 现象 | 常见原因与检查步骤 | 处理建议 |
|---|---|---|
| `仅允许回环 IP 地址` | `--base-url` 使用了 `localhost`、主机名、远端地址，或含 URL 用户名/密码、query、fragment。 | 使用字面 IP，例如 `http://127.0.0.1:8000/v1` 或 `http://[::1]:8000/v1`。客户端拒绝远端地址是设计约束，不要试图用 DNS 名绕过。 |
| `本地模型连接失败`、连接被拒绝 | 服务未启动、端口不对、Harness 与服务处于不同网络命名空间，或连接超时。 | 确认服务监听地址/端口、base URL 和网络命名空间。容器中的 `127.0.0.1` 指向当前容器；单纯把对端地址改为主机名/容器 IP 不满足客户端的 loopback 限制。必要时增加 `--timeout`，但它只调整单次 HTTP 请求上限。 |
| HTTP 404 | 路径前缀或服务路由不匹配，或 base URL 已包含 `/chat/completions` 而被重复拼接。 | `--base-url` 填 API 前缀，例如 `http://127.0.0.1:8000/v1`；Harness 会在末尾追加 `/chat/completions`。对照服务端日志检查实际请求路径。 |
| 模型服务重定向被拒绝 | 服务把请求重定向到另一条 URL；Harness 不跟随重定向。 | 直接配置最终的本机 API 地址，检查服务端/代理路由；不要通过重定向绕开 loopback 限制。 |
| HTTP 401 / 403 | 服务要求认证，key 未设置或不正确。 | 如服务要求 Bearer key，设置 `HARNESS27_API_KEY` 后重试；不要把 key 粘贴进 issue、终端截图、任务提示词或共享轨迹。注意启用 Shell 会让命令继承环境变量。 |
| HTTP 400 或“模型名、工具调用支持”相关错误 | 模型别名不存在，服务不支持请求中的 `tools` / `tool_choice`，或 parser/template 不匹配。 | 检查 `--model` 是否是服务注册名及服务日志。确认当前模型和引擎版本支持原生工具调用；仅能生成文本不够。不要把 API key 或包含提示词的响应体贴进公开报告。 |
| `本地服务返回了无效的 Chat Completions 响应` | 缺少 `choices[0].message`，assistant role 不正确，或 `content` 不是字符串/空值。 | 对照[部署与兼容性指南](DEPLOYMENT_GUIDE.md)核验响应结构和服务版本；客户端为避免泄露数据不会打印原始 HTTP 错误响应体。查看本机服务日志时注意其中可能有提示词或敏感内容。 |
| 模型写出“我将读取文件”，但没有实际读取 | 模型返回了普通文本，没有原生 `assistant.tool_calls`；或工具 parser/template 未生效。 | 检查轨迹 `assistant` 事件是否有 `message.tool_calls`，以及后续是否有 `tool` 事件。配置好该模型对应的 parser/template 后，用只读文件任务重新验证。代码块中的伪调用不会执行。 |
| 工具调用结构无效、参数不是 JSON | 服务或模型输出不符合原生 function tool calling 协议，`arguments` 不是 JSON 字符串，调用缺少 ID/name，或一轮超过 16 次调用。 | 查看脱敏后的轨迹字段及服务日志；核对服务端模板/parser 和模型版本。Harness 不会把普通文本猜测成命令或工具参数。 |
| 文件没写入 | CLI 只在交互终端接受精确输入 `yes`；非交互环境自动拒绝。也可能是路径越界、受保护目录、文件过大或文件系统错误。 | 仅在可信 workspace 中，通过交互终端检查显示的完整参数后决定是否输入 `yes`。单次写入 UTF-8 内容上限为 32 KiB。不要通过自定义审批回调或 benchmark 自动批准来掩盖隔离问题。 |
| 没有 `shell` 工具 | CLI 默认关闭 Shell；benchmark case 的 metadata 可能是 `disabled`，或 `required` case 因未显式授权而跳过。 | 普通 Harness 仅在命令显式包含 `--allow-shell` 时暴露 Shell，且仍逐次交互审批。benchmark 的 `--allow-shell` 会自动批准模型命令，仅能在外部隔离环境中使用。参阅[安全部署操作说明](SECURITY_OPERATIONS.md)。 |
| `step_limit` / `context_limit` / `length_truncated` | 多轮工具任务超预算、JSON 字符数接近限制、单次生成 token 用尽，或服务端上下文设置较小。字符预算不等于模型 token 预算。 | 简化/拆分任务，检查服务端上下文长度；根据需要调整 `--max-steps`、`--max-context-chars` 或 `--max-tokens`。增加预算会增加资源消耗，不保证结果正确。 |
| Benchmark 显示 `skipped` | 多数情况下是 required Shell case 未显式 opt-in；也可能该 case 没有执行。 | 查看 JSON 报告中的 `skip_reason`。先运行 `python benchmark/runner.py --list-cases`。不要仅为消除 `skipped` 在未隔离的主机上加 `--allow-shell`。 |
| Benchmark 显示 `failed`、`error`，但进程退出码为 0 | 任务 verifier 失败是有效评测结果，不等同于 Runner 基础设施错误；全部 case 执行结束时，Runner 可能仍以 0 退出。 | 以 JSON 报告的每个 `results[].status` 和 `summary` 为准；`error` 与 `skipped` 不计入 verifier pass/fail 分母。使用 `--keep-workspaces` 复盘任务文件，报告和工作区可能包含敏感数据。 |
| 轨迹或报告含敏感信息 | Agent JSONL 轨迹会记录任务、模型输出、工具参数和工具结果；benchmark 报告可能含错误摘要、verifier 输出和 workspace 路径。 | 限制目录访问，按组织保留策略清理；公开提交前检查并脱敏。POSIX 文件权限不能替代密钥管理或组织的数据保留政策。 |

## 3. Benchmark 专项检查

```bash
# 不连模型，只检查当前用例是否可发现
python benchmark/runner.py --list-cases

# 先跑禁用 Shell 的单用例，报告使用唯一文件名
python benchmark/runner.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model local-model \
  --case case_04_csv_reconciliation \
  --report ./.harness27/benchmark/results/triage-run-001.json
```

再次运行时请换成一个未使用过的报告文件名；若目标文件已存在，Runner 会替换它。报告状态的解释和字段详见[能力评测手册](BENCHMARK_GUIDE.md)。若需要保留工作区进行诊断，可使用 `--keep-workspaces`；请同时按敏感数据处理工作区。当前 smoke suite 未在实际 27B 模型上测得成功率，mock 测试通过不能当成模型实测。

## 4. 提交问题报告前

请提供：Python 版本、Harness commit、推理引擎/版本、模型服务别名、非敏感参数、最小可复现任务、错误类别和复现步骤。不要直接附上完整 JSONL 轨迹、服务端请求/响应、私有 workspace 或模型权重文件；这些可能含凭据、源码、个人数据或完整提示词。若必须提供片段，先移除密钥与业务数据，并只保留复现所需字段。

安全边界与外部隔离建议见[安全部署操作说明](SECURITY_OPERATIONS.md)；协议前置条件见[本机服务部署与兼容性指南](DEPLOYMENT_GUIDE.md)。

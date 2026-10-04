# Harness27

基于 **Python 3.10+** 的离线 Agent 执行框架，通过本机 OpenAI 兼容的 `POST /v1/chat/completions` 接口调用已部署的 27B 模型。Python 运行时仅使用标准库，无云端 SDK、遥测或自动下载。

> 这是 Agent harness，不负责训练、加载模型权重或 GPU 推理；仓库另含一套早期本地 benchmark runner（见下文），不是完整行业基准。权重加载和推理由 vLLM、Ollama、llama.cpp 等独立服务负责。模型规模不被客户端强制校验，实际使用的 27B 模型由服务端决定。

完整文档： [使用说明](docs/USER_GUIDE.md) · [部署与兼容性](docs/DEPLOYMENT_GUIDE.md) · [故障排查](docs/TROUBLESHOOTING.md) · [安全部署](docs/SECURITY_OPERATIONS.md) · [使用场景实例](docs/USE_CASES.md) · [能力评测手册](docs/BENCHMARK_GUIDE.md) · [流程改进方案](docs/PROCESS_IMPROVEMENT.md) · [本地过程分析](docs/ANALYTICS.md) · [系统设计](docs/DESIGN.md) · [文档索引](docs/README.md)

## 快速开始

### 1. 准备本机模型服务

需提前准备推理引擎、依赖、模型权重与 tokenizer。断网机器应事先完成传输；本仓库不包含权重。服务必须支持：

- Chat Completions 消息协议；
- `tools`、`tool_choice: auto` 和原生 `assistant.tool_calls`；
- 接收 `role: tool` 和 `tool_call_id` 工具结果。

仅能生成文本、但不能生成原生工具调用的模型/聊天模板不能直接用于本应用。不同模型的工具解析器不同，需要依照所安装推理引擎及模型的说明配置，不要仅凭“OpenAI 兼容”判断其支持工具调用。

**vLLM 示例模板（Linux，已安装 vLLM 和本地权重）：**

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
# 必须将下面两个值改成你的本地权重目录及该模型适用的解析器。
export MODEL_DIR=/absolute/path/to/your-27b-model
export TOOL_PARSER=your_model_supported_parser
vllm serve "$MODEL_DIR" \
  --served-model-name local-27b \
  --host 127.0.0.1 --port 8000 \
  --enable-auto-tool-choice --tool-call-parser "$TOOL_PARSER"
```

这不是适用于所有 27B 模型的通用启动命令：有些模型还需要专用 chat template、量化参数、上下文长度和多卡设置。27B 的 FP16/BF16 权重约 54 GB（十进制），INT4 理论权重约 13.5 GB；实际运行还需量化元数据、KV cache 和其他内存，不能据此保证某张显卡能运行。

其他本机服务的连接参数：

| 服务 | `--base-url` 示例 | `--model` |
|---|---|---|
| vLLM | `http://127.0.0.1:8000/v1` | `--served-model-name` 的值 |
| Ollama | `http://127.0.0.1:11434/v1` | 已在本机安装且支持 tools 的模型名 |
| llama.cpp | `http://127.0.0.1:8080/v1` | 该服务注册的模型名；需启用适配的工具调用模板 |

### 2. 运行 harness

在仓库根目录直接运行，无需安装依赖：

```bash
mkdir -p workspace
python -m harness27 \
  --model local-27b \
  --base-url http://127.0.0.1:8000/v1 \
  --workspace ./workspace \
  '列出当前文件，然后创建一个带类型标注的 Python 斐波那契函数和测试文件。'
```

写入文件会显示完整参数，并要求在交互终端中输入 `yes`。非交互运行自动拒绝写入和命令执行，不提供绕过审批的 CLI 开关。

可选安装 CLI 入口（需事先具备 setuptools 等构建依赖）：

```bash
python -m pip install --no-index --no-build-isolation -e .
harness27 --model local-27b '查看工作目录里的文件'
```

启用命令工具：

```bash
python -m harness27 --model local-27b --workspace ./workspace \
  --allow-shell '检查当前 Python 项目，运行测试并分析结果。'
```

每条 Shell 命令仍需人工确认。**Shell 不是沙箱**，启用前请阅读安全说明。

如本地服务要求 API key，可设置环境变量 `HARNESS27_API_KEY`；不会把 key 写进请求轨迹。环境变量本身仍可能被启用的 Shell 读取。

## 功能与预算

- 多轮 `模型 → 工具 → 模型` 执行，串行处理每轮工具调用，最多 16 个。
- 工具：`list_files`、`read_file`、`write_file`；可选 `shell`。
- 路径限制在指定 workspace 内，包括解析符号链接；禁止文件工具访问 `.git`、`.harness27`。
- 文件读写及 Shell 返回文本上限 32 KiB；目录单次最多列出 200 项。
- Shell 默认关闭；启用后单条命令超时为 30 秒。在 POSIX 上清理同进程组子进程。
- 模型参数：`--temperature 0.2`、`--max-tokens 2048`、`--timeout 120`。
- 执行预算：`--max-steps 12`、`--max-context-chars 100000`。
- 超预算明确停止，不自动丢弃历史或伪造成功；字符预算不等价于 tokenizer 的 token 数，需根据实际模型上下文调整。
- 无自动重试，避免请求重试与工具副作用造成意外重复执行。

完整参数：`python -m harness27 --help`。

## 轨迹与返回值

每次运行写入当前目录的 `.harness27/runs/<时间>-<ID>.jsonl`，逐条 flush，包含任务、模型输出、工具调用参数与结果、推理耗时和结束状态。文件以 `0600` 权限创建（POSIX）。可用于审计和定位失败，不支持自动恢复执行。

退出码：

| 代码 | 含义 |
|---|---|
| 0 | 模型给出了最终回答，不代表已通过独立正确性验证 |
| 1 | 模型连接、协议、文件系统或配置错误 |
| 2 | 轮数/上下文预算耗尽，或 CLI 参数错误 |
| 130 | 用户中断 |

## 离线与安全边界

1. 客户端只允许回环 **IP**（`127.0.0.1` / `[::1]` 等），拒绝域名、远程 IP 和 HTTP 重定向，并忽略代理环境变量。容器部署时 harness 必须能在同一网络命名空间连接模型服务。
2. 这些限制只约束模型 HTTP 客户端。模型服务自身是否联网需单独配置；启用的 Shell 也可能联网。真正断网请使用主机/容器网络策略。
3. 文件工具的路径校验不是 OS 级沙箱，不能抵御恶意并发修改目录/符号链接、预先放置的敏感硬链接或所有特殊文件系统场景。只使用专门的、可信的工作目录，不要挂载凭据或个人文件。
4. Shell 使用当前用户权限，可访问工作目录外的文件、继承环境变量并启动进程。应在无凭据、无网络、限制 CPU/内存/磁盘的隔离容器中运行，并检查每次审批内容。命令输出先落临时文件，返回值虽然截断，临时磁盘占用仍需 OS 配额约束。POSIX 进程组清理不保证清除主动脱离进程组的进程。
5. Agent 轨迹含任务、工具调用参数/结果、文件内容及模型输出，可能包含敏感信息；请设置合适的存储权限并定期清理。`.gitignore` 默认排除轨迹、workspace 和 models。
6. 模型输入、工具输出和生成的代码均不可信；人工审批与提示词不能替代安全隔离。

## 27B 能力摸底评测

`benchmark/runner.py` 用于串行运行本地模型评测用例，服务地址仍限制为回环 IP。先查看用例，再单跑或重复一组任务：

```bash
python benchmark/runner.py --list-cases
python benchmark/runner.py --case case_04_csv_reconciliation
python benchmark/runner.py --repeat 3
```

若本地模型服务要求 API key，使用 `HARNESS27_API_KEY` 环境变量。每个用例有独立 fixture、任务、元数据（能力类别/难度/技能）和客观 verifier；当前覆盖配置抽取、否定约束、代码修复、CSV 多文件对账、库存补货、多软件包依赖安装计划（仅规划）、支持工单分派、会议室分配规划、制造批次质量复核、生产工单物料齐套核对和组件批次追溯。报告记录 runner/Agent/客户端/工具的 SHA-256 指纹，以及每个用例输入（提示词、fixture、元数据、verifier）的 SHA-256 指纹，便于确认不同运行是否评测了同一版本。结果按用例、类别、难度和技能汇总，包括 verifier 成功率、Agent 完成率、轮数、工具错误、耗时和服务返回的 token 用量。Verifier pass/fail 才计入能力成功率；接口/协议/verifier 异常和跳过会单独统计、不计入该分母。技能标签可重叠，各技能成功率不可相加成总分。重复运行可观察该小型用例集上的稳定性，但服务端未必支持可复现采样。

默认工作区使用唯一临时目录，评测后清理；`--keep-workspaces` 可保留以便复盘。JSON 报告默认写到 `.harness27/benchmark/results/`（权限受限，且已被 Git 忽略），保存逐用例指标、汇总和 verifier 输出；不保存完整对话、工具参数或推理轨迹。自定义路径：`--report ./my-run.json`。

代码修复用例要求运行测试，标记为 `shell=required`，未明确授权时会跳过；需加 `--allow-shell` 才会运行：

```bash
python benchmark/runner.py --case case_03_pytest_repair --allow-shell
```

**高风险：** `--allow-shell` 会自动批准模型生成的任意 Shell 命令，Shell 使用当前用户权限且不是沙箱。只应在没有凭据、无网络并有 CPU/内存/磁盘限制的外部隔离容器中启用；不要把此选项当作安全隔离。Shell 只会出现在元数据允许的用例中，敏感文件约束用例始终禁用 Shell。

这套十一用例是早期 smoke suite，不是代表性行业基准；不同任务、模型模板、量化、采样和推理服务配置都会影响结果。服务端权重校验、量化、tokenizer/chat template/tool parser 版本目前不会由 API 自动探测；跨运行比较时需自行记录部署参数。报告只反映当前配置和这些具体用例，不能据此宣称 27B 模型普遍具备或不具备某种能力。当前仓库**尚未在实际 27B 模型上完成端到端评测**，尚无实测成功率。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试不依赖模型权重，也不访问互联网；包含模拟多轮 Agent、本机分析器、真实回环 HTTP 测试服务、benchmark runner 和各用例 verifier。覆盖文件审批、路径穿越/符号链接、硬链接覆写保护、无效工具参数、调用结构验证、预算、读文件截断、Shell 超时、远程 URL/重定向拒绝，以及敏感文件访问尝试、脱敏过程报告、问卷关联、benchmark 汇总、库存补货 verifier 的输入/数量边界、软件安装计划的版本/依赖排序、支持工单优先级/SLA/时区计算、会议室容量/设备/预订冲突检查、制造质检规格边界/抽样状态、工单 BOM 物料短缺和组件批次追溯与禁用 Shell 检查、评测工作区保护和 Markdown 本地链接/围栏检查。

## 代码结构

```text
harness27/
  client.py     本机推理接口与响应校验
  agent.py      多轮 Agent 状态循环与预算
  tools.py      工作目录文件工具、审批、可选 Shell
  cli.py        命令行、轨迹记录、退出状态
  analytics.py  本地轨迹汇总、问卷关联与脱敏分析报告
  __main__.py   python -m harness27 入口
benchmark/
  runner.py     串行评测、客观验证与 JSON 汇总
  cases/        fixture、任务元数据和独立 verifier
tests/
  test_harness.py
  test_benchmark.py
  test_benchmark_runner.py
  test_analytics.py
```

在 Python 中也可直接组合 `LocalClient`、`Tools` 和 `Agent`。`Tools` 默认拒绝任何写入和 Shell 操作；若自定义 `approve(name, args)` 回调，调用方负责实现真实的授权机制。`trace(event, data)` 回调可用于接入自定义审计存储。

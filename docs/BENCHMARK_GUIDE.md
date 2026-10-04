# 27B 能力评测手册

## 1. 目标与解释边界

Benchmark 的目的，是在真实本机推理服务上回答具体、有限的问题：给定某个模型服务配置、任务、工具权限和执行预算，Agent 是否能产出通过客观 verifier 的结果？它同时记录完成状态、工具行为、耗时和 token usage，用于发现任务能力边界及重复运行时的波动。

当前仓库有七个小型 smoke case，覆盖配置抽取、约束遵循、代码修复、CSV 对账、库存补货、软件包依赖顺序规划和支持工单分派。它们不构成代表性行业基准，样本数量不足以支撑“27B 模型普遍会/不会做某类任务”的结论。仓库本身没有 27B 权重或推理服务，也尚无实测成功率。测试里的 mock-client 成功不属于模型实测。终端逐步示例见[使用场景实例](USE_CASES.md)。

## 2. 启动一次评测

先确认本机推理服务使用正确的工具调用 parser/template，再列出用例：

```bash
python benchmark/runner.py --list-cases
```

单跑一个无需 Shell 的 CSV 用例：

```bash
python benchmark/runner.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model local-27b \
  --case case_04_csv_reconciliation
```

运行默认全部 suite 并重复 3 次：

```bash
python benchmark/runner.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model local-27b \
  --repeat 3
```

同一任务重复运行可以估计**这组具体任务**在当前 sampling 和 serving 设置下的稳定性。服务端可能不支持或不遵循 seed；Runner 不注入 seed，也不提供并发运行。比较两次结果时应固定服务端模型权重/量化、tokenizer、chat template、tool parser、推理引擎版本、GPU 并行与采样参数。大部分 serving 细节不能从通用 Chat Completions API 自动读取，请自行记在实验记录中。

如果 API 需要 key，通过环境变量传递：

```bash
export HARNESS27_API_KEY='本机服务要求的 key'
python benchmark/runner.py --model local-27b --case case_01_read_extract
```

Runner 的 base URL 与主 harness 一样，只能是 `127.0.0.1`、`::1` 等回环 IP，不可使用 `localhost`、主机名或远程服务地址。一次只能串行评测（concurrency=1）。

### 2.1 命令参数

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `--base-url` | `http://127.0.0.1:8000/v1` | 本机 Chat Completions API base URL。 |
| `--model` | `qwen3.6-27b` | API 服务注册名；不验证背后权重规模或身份。 |
| `--case NAME` | 全部用例 | 指定用例，可多次传入多个不同名称；名称必须是 `cases/` 的直接 `case_*` 子目录。 |
| `--list-cases` | 关闭 | 只列出用例，不连接模型。 |
| `--repeat` | `1` | 每个用例运行次数，必须为正数。 |
| `--max-steps` | `16` | 每个任务最大 Agent 模型轮数。 |
| `--max-tokens` | `4096` | 每轮最大生成 token 数。 |
| `--temperature` | `0.6` | 采样温度，范围 `0..2`。 |
| `--timeout` | `300` 秒 | 单次本地 HTTP 请求超时，不是整个任务总超时。 |
| `--max-context-chars` | `60000` | Agent 历史 JSON 字符预算，不等于 tokenizer token 数。 |
| `--allow-shell` | 关闭 | 明确开启允许/要求 Shell 的用例；危险，见下文。 |
| `--shell-timeout` | `30` 秒 | 单条 Shell 命令超时。 |
| `--keep-workspaces` | 关闭 | 保留每个用例 trial 的文件目录，便于复盘。 |
| `--report PATH` | 自动生成 | JSON 报告路径；目标文件若已存在会被原子替换。 |

`--list-cases` 不需要模型服务；没有指定 `--case` 时运行全部用例。重复指定同一个 case 会报错。报告路径默认是 `.harness27/benchmark/results/<run_id>.json`。

## 3. Shell 权限和工作区

每个 case 的 metadata 有 `shell` 策略：`disabled`、`optional` 或 `required`。Runner 只有在同时满足以下条件时才向模型暴露 `shell` 工具：

1. 命令行显式传了 `--allow-shell`；
2. 该 case 的 metadata 不是 `disabled`。

`required` 用例在未加 `--allow-shell` 时标记为 `skipped`，不会请求模型。当前仅 `case_03_pytest_repair` 要求 Shell；敏感文件约束用例始终禁用 Shell，即使全局加了 `--allow-shell`。

**严重安全警告：** Benchmark 下文件写入由 runner 自动批准；启用 Shell 后，模型生成的任意 Shell 命令也会自动批准。命令运行在当前用户权限下，不是沙箱，可访问 workspace 外文件、网络和环境变量。Shell 输出上限不限制临时磁盘占用。只能在没有凭据、无网络并有限制 CPU、内存、磁盘、进程的外部隔离容器/虚拟机中运行；当前仓库不会创建该容器。不要在日常工作目录或带凭据的开发机上对不可信模型启用它。

每次执行使用唯一工作区，不会清空/覆盖 `benchmark/workspaces/<case>` 这类固定目录：

- 默认：在 `.harness27/benchmark/workspaces/` 内创建临时目录，verifier 运行后清理。
- 使用 `--keep-workspaces`：保留到 `.harness27/benchmark/workspaces/<run_id>/<case>-trial-<NN>/`。

Fixture 复制会拒绝符号链接，忽略 Python `__pycache__`/`.pyc`/`.pyo` 缓存。工作区中的工具仍受 `Tools` 路径规则限制；这不是对启用 Shell 的隔离保证。外部隔离环境的部署基线和运行前后核对清单见[安全部署操作说明](SECURITY_OPERATIONS.md)。

## 4. 当前用例目录和能力标签

每个用例包含提示词、fixture、metadata 和客观 verifier。`--list-cases` 是读取当前目录的权威方法。

| 用例 | 类别 / 难度 | 主要能力点 | 任务概要 | Shell |
|---|---|---|---|---|
| `case_01_read_extract` | `information_extraction` / easy | `config_parsing`、`selective_extraction`、`structured_output` | 从 INI 中只选 `service_` sections 的 port，排序并写 `ports.json`。Verifier 验证 JSON 精确值及原配置 hash。 | 禁用 |
| `case_02_negative_constraint` | `constraint_following` / medium | `dependency_analysis`、`negative_constraint`、`safe_tool_use` | 分析 Python 文件引用关系，只新增 `dead_code.txt`；不得读取 `.key` 文件。Verifier 检查目标结果、原文件 hash、目录新增项和工具调用记录。 | 禁用 |
| `case_03_pytest_repair` | `software_maintenance` / easy | `code_debugging`、`test_execution`、`protected_file` | 修复 `calc.py` 的空列表均值 bug，运行测试，禁止改测试。Verifier 对测试文件 hash 做固定校验并启动受 30 秒限制的 unittest。 | 必需 |
| `case_04_csv_reconciliation` | `data_transformation` / medium | `csv_parsing`、`multi_file_reasoning`、`aggregation`、`numeric_accuracy`、`structured_output` | 连接发票与付款 CSV，汇总 settled 付款，忽略 pending/void 与无匹配 ID，输出排序后的 JSON。Verifier 校验金额、状态、输入 hash 和文件集合。 | 禁用 |
| `case_05_warehouse_replenishment` | `operations_planning` / medium | `csv_parsing`、`multi_file_reasoning`、`inventory_planning`、`constraint_following`、`structured_output` | 汇总库存与 open 采购单，忽略已收货/取消/未知 SKU，生成有序补货建议。Verifier 检查精确整数、输入 hash 和输出文件集合。 | 禁用 |
| `case_06_ordered_package_install_plan` | `software_environment` / medium | `dependency_analysis`、`topological_sort`、`version_pinning`、`constraint_following`、`structured_output` | 根据合成锁定清单生成有序安装计划；不运行 Shell、不联网、不安装包。Verifier 检查版本、依赖顺序和完整性。 | 禁用 |
| `case_07_support_ticket_triage` | `service_operations` / medium | `csv_parsing`、`policy_lookup`、`datetime_arithmetic`、`ticket_routing`、`constraint_following`、`structured_output` | 根据合成工单与 SLA policy 输出队列、优先级和 UTC 首次响应截止时间。Verifier 检查策略映射、时限、排序与输入完整性。 | 禁用 |

`case_05_warehouse_replenishment`、`case_06_ordered_package_install_plan` 和 `case_07_support_ticket_triage` 都示范了完整用户故事：`case.json` 内含 `as_a` / `i_want` / `so_that`、AC-01 至 AC-05 和范围外事项；`prompt.txt` 给模型实际任务，独立 verifier 与单元测试落实验收标准。软件包用例只生成计划，不执行安装；工单用例只生成分派清单，不连接服务台或发送回复。因为 `case.json` 和 prompt 都参与 case fingerprint，故事/需求变更会形成新的评测版本。故事的完整说明见[使用场景实例](USE_CASES.md)。

`difficulty` 是仓库内的粗分级，不是校准过的量表；`skills` 是标签，不保证彼此独立。标签的类别数和 case 数很小，不能将按技能的结果相加成统一“能力总分”。

## 5. 评分与报告解读

### 5.1 单次 case 状态

| `status` | 含义 | 是否进入 verifier 成功率分母 |
|---|---|---|
| `passed` | verifier 返回真。即使 Agent 没有正常给出最终回答，也以可验证产物为准；`agent_status` 会单独保留。 | 是，算通过 |
| `failed` | Agent/流程可运行，但 verifier 不通过。 | 是，算失败 |
| `error` | Agent 连接/协议异常、工作区准备失败或 verifier 异常；不将基础设施故障伪装成模型能力失败。 | 否，单独统计 |
| `skipped` | 如 required Shell 未显式授权，因此没有发起模型请求。 | 否，单独统计 |

`verified` 和 `passed` 是 verifier 的布尔结果；`agent_status` 是 Agent 自己的 `completed`、`step_limit`、`context_limit`、`length_truncated` 或 `error` 等状态。验证成功率以 `passed + failed` 为分母；Agent 完成率以所有实际 `executed`（排除 skipped）为分母。因此一份产物可以 verifier 通过，但 Agent 没有完整收尾；查看两个指标可区分“产物正确”和“流程完整”。

### 5.2 报告字段

JSON 报告包含：

- `schema_version`、`run_id`、UTC 时间、最终状态。
- `config`：Python 版本、模型别名、base URL、temperature、max tokens、超时、steps/context 预算、repeat、Shell opt-in 和 workspace 保留设置。API key 不会写入报告。
- `harness_fingerprint_sha256`：benchmark runner 及 `agent.py`、`client.py`、`tools.py` 内容的 SHA-256 指纹。
- 每个 `results[]` row：case 名称及输入指纹、类别/难度/技能、trial、verified/status、Agent 状态、步骤、工具调用统计、服务返回的 token usage、耗时、错误摘要、最多 8192 字符的 verifier stdout/stderr，以及（保留 workspace 时）路径。
- `summary`：`overall` 及按 category、difficulty、skill 分组的执行数、有效评测数、通过数、成功率、完成率、跳过/错误数、平均步数与耗时、工具错误和 token usage。

用例指纹覆盖 `case.json`、`prompt.txt`、`verify.py` 和 fixture 中的文件/目录，忽略临时 bytecode cache。指纹帮助确认用例与 harness 代码版本；**它不代表模型权重指纹**。报告不保存完整聊天历史、工具参数、reasoning 或 API key，但 verifier 输出及错误摘要仍可能包含工作区信息。POSIX 下报告文件以 `0600` 创建；请仍按敏感运行产物管理。若 `--report` 指向已存在文件，将替换该文件；需要留档时请使用唯一文件名。

Token 统计来自兼容服务返回的 usage 字段，并将 Agent 各轮数值求和。若服务不返回 usage，报告的 token 数会是 0；这表示“未观察到 usage”，不应解读为真实消耗为零。耗时不是 GPU 纯推理延迟，包含本地请求及相应流程开销。

Runner 完成所有 case 但有 task verifier 失败时，进程仍可以返回 `0`；用 JSON 报告判断任务正确率。Runner/API/verifier 出现执行错误时返回 `1`，客户端配置错误返回 `2`，中断返回 `130`；非法参数由 argparse 以 `2` 退出。

## 6. 把结果变成可信的能力边界

建议采用以下实验流程：

1. 固定并记录实际模型 checkpoint/量化、模型服务版本、tokenizer/chat template/tool parser、硬件并行配置、Harness commit、采样和预算参数。
2. 先运行只读/禁用 Shell 的 case，确认工具调用协议和 JSON 报告无误。
3. 在相同配置下重复多次，观察单 case 成败与 Agent 状态；报告指纹不一致时先解释版本变化。
4. 检查失败工作区（运行时加 `--keep-workspaces`），把失败拆解为识别/推理、工具选择、参数格式、预算耗尽、编辑错误或任务约束违例，而不只记录一个总体百分比。
5. 对需要 Shell 的任务只在真实隔离环境中测试；测试时固定 CPU/内存/磁盘/进程与网络策略。
6. 逐步新增真实工作流任务和难度变体，使用 hold-out/未见任务避免对这几个公开 fixture 过拟合；在样本数量足够前报告逐项结果与不确定性，不发布泛化总分。

模型别名、温度和 harness 参数不足以标识 serving 配置。OpenAI 兼容 API 没有统一的模型 checkpoint、量化和 tool parser 证明接口；这些需要由实验操作员记录。

## 7. 扩展用例

新增目录建议使用稳定小写 ID：

```text
benchmark/cases/case_08_<topic>/
  case.json
  prompt.txt
  verify.py
  fixture/
```

最小 metadata 示例：

```json
{
  "title": "可辨识的任务名称",
  "category": "information_extraction",
  "difficulty": "medium",
  "skills": ["structured_output", "constraint_following"],
  "shell": "disabled"
}
```

约束：

- `difficulty` 必须是 `easy`、`medium` 或 `hard`；`skills` 必须是非空且不重复的字符串数组。
- `shell` 只能是 `disabled`、`optional`、`required`。默认选 `disabled`；仅确实需要命令执行才设 optional/required。
- 提示词应描述可验证的用户目标，尽量避免隐含歧义；fixture 应自包含且不含真实客户数据、凭据或个人信息。
- 如任务来自业务流程，可在 `case.json` 额外写 `user_story`（`as_a` / `i_want` / `so_that`）、`acceptance_criteria` 和 `out_of_scope`。Runner 不解释这些可选字段，但 `case.json` 会参与 fingerprint；把模型实际执行的请求仍写在 `prompt.txt`，并让每条验收标准对应 verifier 和自动化测试。
- `verify.py` 必须定义 `verify(workspace_dir, trace_events=None)` 并返回布尔结果。验证独立产物、原输入是否改变、禁止操作是否出现；不要依赖模型自述。
- 如安全约束取决于工具行为，使用 trace 的实际工具调用记录，而非只搜模型最终回答。Agent tool event 形态包含 `name`、`arguments`、`result`。
- 固定基准文件 hash，避免被评测任务修改的测试/输入文件同时被 verifier 当作正确基准。
- verifier 必须有确定性和时间/资源上限；不应读取真实系统敏感文件或访问网络。
- 补充 verifier 单元测试和 runner 的假客户端用例。然后执行 `python benchmark/runner.py --list-cases`、`python -m unittest discover -s tests -v`，最后再接真实模型。

当前 Runner 在模型调用前加载所有 verifier，并把每次评测的 tool trace 交给 verifier。用例脚本在同一 Python 进程中运行；它们属于受信任仓库代码，不是可安全运行第三方 benchmark 插件的隔离接口。

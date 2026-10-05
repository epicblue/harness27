# case_14_maintenance_event_triage：按生产影响和设备关键性整理维修事件

[← 返回使用场景总览](../USE_CASES.md) · [能力评测手册](../BENCHMARK_GUIDE.md)

**类别：** `maintenance_planning`　 **难度：** `medium`　 **Shell：** 禁用

> 本页描述的是合成数据上的 review-only benchmark 任务。产物仅供人工复核；不代表实际部署或 27B 模型评测结果，也不构成设备操作、质量放行或生产指令。

## 用户故事

> 作为设备维护协调员，我想依据安全标记、产线影响和设备关键性给合成维修事件分级并排序，以便维护团队可以先人工查看影响最高的事件并参考政策响应窗口。

## 业务背景与输入

把合成维护事件依照明确的安全条件、生产影响和资产关键性转换成可供维护协调员人工查看的有序队列。

| 合成输入 | 内容与用途 |
|---|---|
| [`maintenance_events.csv`](../../benchmark/cases/case_14_maintenance_event_triage/fixture/maintenance_events.csv) | 合成事件 ID、资产、观察时间、安全标记、生产影响和关键性。 |
| [`maintenance_policy.json`](../../benchmark/cases/case_14_maintenance_event_triage/fixture/maintenance_policy.json) | 首个命中规则、条件到优先级映射、响应窗口和排序顺序。 |

## 计算规则与结果契约

- 严格按 policy 的 `rule_precedence` 应用第一条命中规则，安全标记优先。
- 非安全事件按 policy 区分停线、关键设备降产、其他降产和无生产影响，并查表获得响应窗口。
- 按 `priority_order`、事件时间和 `event_id` 排序；输出仅是审核队列。

- **唯一允许新增的文件：** `maintenance_queue.json`（JSON 数组；每项仅包含 `event_id`、`asset_id`、`priority`、`response_window_minutes`）。
- **完整验收准则：**
  - **AC-01：** 每个事件恰好输出一条记录，字段仅为 event_id、asset_id、priority、response_window_minutes。
  - **AC-02：** 优先级严格按 maintenance_policy.json 的条件顺序判定，安全标记优先于其他规则。
  - **AC-03：** response_window_minutes 按映射后的优先级从 policy 查找。
  - **AC-04：** 按 priority_order、observed_at_utc、event_id 升序输出。
  - **AC-05：** 只新增 maintenance_queue.json；不派发真实维修工单、不控制设备、不调用 Shell 或外部系统。

## 人工复核重点

- 核对规则优先级，不要让后续的普通生产影响条件覆盖安全标记。
- 响应窗口必须来自政策映射；不能自行增加维修步骤或诊断根因。
- 优先级不等于已派工、停机、报警或对实际设备的操作授权。

## 范围外与安全边界

- 诊断根因或提供维修操作步骤
- 自动停机、复位或控制设备
- 创建或派发真实维修工单
- 联系操作员或修改 CMMS
- 只处理此用例目录中的合成 fixture；只在 Runner 创建的独立评测工作区生成指定 JSON。
- `shell` 为 `disabled`；Agent 不调用 Shell/网络工具，也不访问 PLC、打印机、MES、ERP、WMS、QMS、CMMS、APS 或其他外部系统。
- verifier 检查 fixture 完整性、输出 schema/内容、工作区文件边界及禁用工具轨迹；通过只表示通过此固定合成任务的自动校验。

## 复现与验证

离线运行新增用例的 verifier 单测（不连接模型服务）：

```bash
python -m unittest tests.test_benchmark.BenchmarkVerificationTests.test_cases_12_to_21_manufacturing_verifiers_are_deterministic_and_shell_free -v
```

如需通过 Runner 向已配置的本机兼容服务发起此 case，可将 `local-27b` 替换为服务实际注册的模型名：

```bash
python benchmark/runner.py --model local-27b --case case_14_maintenance_event_triage
```

上面的命令是使用说明，不表示本项目已对真实 27B 模型运行或获得任何成功率；本 case 的 Shell 权限始终禁用。

## 实现文件

- [用例元数据](../../benchmark/cases/case_14_maintenance_event_triage/case.json)
- [模型任务提示词](../../benchmark/cases/case_14_maintenance_event_triage/prompt.txt)
- [确定性 verifier](../../benchmark/cases/case_14_maintenance_event_triage/verify.py)

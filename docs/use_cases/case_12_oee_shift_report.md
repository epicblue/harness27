# case_12_oee_shift_report：汇总生产班次的 OEE 指标

[← 返回使用场景总览](../USE_CASES.md) · [能力评测手册](../BENCHMARK_GUIDE.md)

**类别：** `operations_metrics`　 **难度：** `medium`　 **Shell：** 禁用

> 本页描述的是合成数据上的 review-only benchmark 任务。产物仅供人工复核；不代表实际部署或 27B 模型评测结果，也不构成设备操作、质量放行或生产指令。

## 用户故事

> 作为生产主管，我想按产线和班次从合成生产计数计算可用率、性能、质量率和 OEE，以便团队可以用一致口径比较班次表现并安排人工复盘，而不是依赖手工表格计算。

## 业务背景与输入

将计划生产时间、停机时间、总产量、良品数与标准节拍统一换算为班次级 OEE 指标，作为团队进行人工班次比较与复盘的输入。

| 合成输入 | 内容与用途 |
|---|---|
| [`oee_policy.json`](../../benchmark/cases/case_12_oee_shift_report/fixture/oee_policy.json) | 比例输出的小数精度等明确计算政策。 |
| [`shift_metrics.csv`](../../benchmark/cases/case_12_oee_shift_report/fixture/shift_metrics.csv) | 合成的产线/班次、计划分钟、停机分钟、总产量和良品数。 |

## 计算规则与结果契约

- `run_minutes = planned_minutes - downtime_minutes`。
- `availability = run_minutes / planned_minutes`，`performance = ideal_cycle_seconds × total_units / (run_minutes × 60)`，`quality = good_units / total_units`。
- `oee = availability × performance × quality`；按 policy 的小数精度舍入，不将比例改写成百分数。
- 结果按 `shift_id`、`line_id` 升序；只允许写指定 JSON 文件。

- **唯一允许新增的文件：** `oee_report.json`（JSON 数组；每项仅包含 `line_id`、`shift_id`、`run_minutes`、`availability`、`performance`、`quality`、`oee`）。
- **完整验收准则：**
  - **AC-01：** 每个输入班次恰好输出一条记录，字段仅为 line_id、shift_id、run_minutes、availability、performance、quality、oee。
  - **AC-02：** run_minutes = planned_minutes - downtime_minutes；可用率、性能和质量率按 prompt 公式计算。
  - **AC-03：** OEE 等于 availability × performance × quality；比例按 policy 的小数位数四舍五入。
  - **AC-04：** 按 shift_id、line_id 升序输出，计数为整数，比例为 JSON 数值。
  - **AC-05：** 只新增 oee_report.json；不修改输入、不调用 Shell、联网或控制设备。

## 人工复核重点

- 确认停机时间已从计划分钟扣除，并在性能公式中将运行分钟换算为秒。
- 比例保持 0–1 的 JSON 数值；舍入位数读取 policy，不转成百分数。
- OEE 是三个比例的乘积，不应把“高 OEE”解释成设备状况或绩效责任结论。

## 范围外与安全边界

- 更改设备速度或生产参数
- 控制产线或采集实时传感器
- 将 OEE 结果写入真实 MES
- 推断停机原因或绩效责任
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
python benchmark/runner.py --model local-27b --case case_12_oee_shift_report
```

上面的命令是使用说明，不表示本项目已对真实 27B 模型运行或获得任何成功率；本 case 的 Shell 权限始终禁用。

## 实现文件

- [用例元数据](../../benchmark/cases/case_12_oee_shift_report/case.json)
- [模型任务提示词](../../benchmark/cases/case_12_oee_shift_report/prompt.txt)
- [确定性 verifier](../../benchmark/cases/case_12_oee_shift_report/verify.py)

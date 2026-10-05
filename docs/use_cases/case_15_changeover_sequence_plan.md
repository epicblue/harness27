# case_15_changeover_sequence_plan：按优先级和交期生成换型顺序计划

[← 返回使用场景总览](../USE_CASES.md) · [能力评测手册](../BENCHMARK_GUIDE.md)

**类别：** `production_planning`　 **难度：** `medium`　 **Shell：** 禁用

> 本页描述的是合成数据上的 review-only benchmark 任务。产物仅供人工复核；不代表实际部署或 27B 模型评测结果，也不构成设备操作、质量放行或生产指令。

## 用户故事

> 作为生产排程员，我想按既定优先级和交期顺序排列合成工单，并计算相邻产品族之间的换型时间，以便班组可以审核一个透明、可复现的换型计划及其准备时间。

## 业务背景与输入

对给定的一组合成工单应用既定优先级与交期规则，并从换型矩阵计算每张工单前需要的准备分钟数。

| 合成输入 | 内容与用途 |
|---|---|
| [`changeover_policy.json`](../../benchmark/cases/case_15_changeover_sequence_plan/fixture/changeover_policy.json) | 优先级顺序、初始产品族以及产品族间换型分钟矩阵。 |
| [`production_orders.csv`](../../benchmark/cases/case_15_changeover_sequence_plan/fixture/production_orders.csv) | 合成 order ID、产品族、优先级和 UTC 交期。 |

## 计算规则与结果契约

- 固定按 policy 优先级、`due_date_utc`、`order_id` 排序；不搜索更短的全局路径。
- 首单从 `initial_family` 切换到该单产品族；之后从前一张工单的产品族切换。
- 切换分钟由 `changeover_minutes_by_family` 矩阵查得；序号从 1 连续递增。

- **唯一允许新增的文件：** `changeover_plan.json`（JSON 数组；每项仅包含 `sequence`、`order_id`、`product_family`、`setup_minutes_before`）。
- **完整验收准则：**
  - **AC-01：** 每个工单恰好输出一次，字段仅为 sequence、order_id、product_family、setup_minutes_before。
  - **AC-02：** 排序严格按 policy 的 priority_order、due_date_utc、order_id。
  - **AC-03：** 首单从 initial_family 查换型矩阵；其余工单从前一工单 product_family 查矩阵。
  - **AC-04：** 换型分钟数必须与矩阵精确一致，sequence 从 1 连续递增。
  - **AC-05：** 只新增 changeover_plan.json；不启动、暂停或改写生产工单，不调用 Shell 或产线系统。

## 人工复核重点

- 确认首单使用 policy 的初始产品族，后续每一步均引用紧邻的前序工单。
- 排序规则是确定性的业务规则，不是最短换型时间优化。
- 计划不包含未提供的人员、设备可用性、物料或真实产线约束。

## 范围外与安全边界

- 优化全局最短换型路径
- 考虑未提供的设备/人员约束
- 实际下达排程或控制产线
- 修改工单优先级、交期或产品族
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
python benchmark/runner.py --model local-27b --case case_15_changeover_sequence_plan
```

上面的命令是使用说明，不表示本项目已对真实 27B 模型运行或获得任何成功率；本 case 的 Shell 权限始终禁用。

## 实现文件

- [用例元数据](../../benchmark/cases/case_15_changeover_sequence_plan/case.json)
- [模型任务提示词](../../benchmark/cases/case_15_changeover_sequence_plan/prompt.txt)
- [确定性 verifier](../../benchmark/cases/case_15_changeover_sequence_plan/verify.py)

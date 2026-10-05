# case_13_calibration_due_review：生成设备校准到期复核清单

[← 返回使用场景总览](../USE_CASES.md) · [能力评测手册](../BENCHMARK_GUIDE.md)

**类别：** `maintenance_planning`　 **难度：** `easy`　 **Shell：** 禁用

> 本页描述的是合成数据上的 review-only benchmark 任务。产物仅供人工复核；不代表实际部署或 27B 模型评测结果，也不构成设备操作、质量放行或生产指令。

## 用户故事

> 作为计量设备管理员，我想按最近校准日期、校准周期和复核日期生成设备到期状态清单，以便团队可以提前安排人工校准复核，并发现已经超过计划日期的设备。

## 业务背景与输入

根据固定的复核日期、最近校准日期和周期，制作合成设备的到期清单，帮助计量团队人工识别近期需要关注的项目。

| 合成输入 | 内容与用途 |
|---|---|
| [`equipment_calibration.csv`](../../benchmark/cases/case_13_calibration_due_review/fixture/equipment_calibration.csv) | 合成 equipment ID、最近校准日期及校准间隔天数。 |
| [`review_policy.json`](../../benchmark/cases/case_13_calibration_due_review/fixture/review_policy.json) | 复核基准日 `as_of_date` 和 `due_soon_window_days` 提醒窗口。 |

## 计算规则与结果契约

- `due_date = last_calibration_date + interval_days`，按日历日计算。
- 到期日早于复核日为 `overdue`；复核日当天到窗口末日（含）为 `due_soon`；窗口之外为 `current`。
- `days_until_due = due_date - as_of_date`，以有符号整日表示；按到期日和设备 ID 排序。

- **唯一允许新增的文件：** `calibration_review.json`（JSON 数组；每项仅包含 `equipment_id`、`due_date`、`status`、`days_until_due`）。
- **完整验收准则：**
  - **AC-01：** 每台设备恰好输出一条记录，字段仅为 equipment_id、due_date、status、days_until_due。
  - **AC-02：** due_date = last_calibration_date + interval_days；日期按日历日计算。
  - **AC-03：** 按 as_of_date 判断：due_date 早于复核日为 overdue；当日到窗口末日（含）为 due_soon；之后为 current。
  - **AC-04：** days_until_due 为 due_date 与 as_of_date 的有符号日差，按 due_date、equipment_id 升序输出。
  - **AC-05：** 只新增 calibration_review.json；不锁定设备、不修改资产记录、不调用 Shell 或外部系统。

## 人工复核重点

- 检查日期加法使用日历日，而不是假设每月固定天数。
- 复核日当天和提醒窗口最后一天都属于 `due_soon`；逾期天数为负。
- 清单是提醒草案；它不证明仪器实际状态、校准有效性或认证结果。

## 范围外与安全边界

- 执行或认证校准
- 自动锁定/解锁设备
- 更改校准间隔或仪器精度参数
- 写入真实 CMMS、QMS 或资产系统
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
python benchmark/runner.py --model local-27b --case case_13_calibration_due_review
```

上面的命令是使用说明，不表示本项目已对真实 27B 模型运行或获得任何成功率；本 case 的 Shell 权限始终禁用。

## 实现文件

- [用例元数据](../../benchmark/cases/case_13_calibration_due_review/case.json)
- [模型任务提示词](../../benchmark/cases/case_13_calibration_due_review/prompt.txt)
- [确定性 verifier](../../benchmark/cases/case_13_calibration_due_review/verify.py)

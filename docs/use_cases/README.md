# 制造业 benchmark 用户故事

[← 返回使用场景总览](../USE_CASES.md) · [能力评测手册](../BENCHMARK_GUIDE.md)

以下页面分别说明 case 12–21 的业务目标、合成输入、计算规则、验收契约、人工复核重点和安全范围。所有场景均离线可测、Shell 禁用且仅生成 review-only 产物；这些文档不声称已完成真实模型评测。

| 用例 | 用户角色 | 专门故事说明 |
|---|---|---|
| `case_12_oee_shift_report` | 生产主管 | [查看故事说明](case_12_oee_shift_report.md) |
| `case_13_calibration_due_review` | 计量设备管理员 | [查看故事说明](case_13_calibration_due_review.md) |
| `case_14_maintenance_event_triage` | 设备维护协调员 | [查看故事说明](case_14_maintenance_event_triage.md) |
| `case_15_changeover_sequence_plan` | 生产排程员 | [查看故事说明](case_15_changeover_sequence_plan.md) |
| `case_16_supplier_receipt_reconciliation` | 来料计划员 | [查看故事说明](case_16_supplier_receipt_reconciliation.md) |
| `case_17_packaging_label_audit` | 包装质量检验员 | [查看故事说明](case_17_packaging_label_audit.md) |
| `case_18_scrap_reason_summary` | 制造质量分析员 | [查看故事说明](case_18_scrap_reason_summary.md) |
| `case_19_downtime_duration_summary` | 设备可靠性分析员 | [查看故事说明](case_19_downtime_duration_summary.md) |
| `case_20_packout_estimate` | 包装计划员 | [查看故事说明](case_20_packout_estimate.md) |
| `case_21_capacity_gap_review` | 产能计划员 | [查看故事说明](case_21_capacity_gap_review.md) |

这些单页文档与 `case.json`、`prompt.txt` 和 verifier 一同描述固定的合成任务。实际评测须由使用者自行配置并连接本机服务；本仓库文档和单测不是模型实测结果。

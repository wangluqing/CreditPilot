# CreditPilot V0.1 演示评分与模拟策略

- 模型版本：`demo-score-v1`
- 规则版本：`demo-rules-v1`
- 策略版本：`demo-policy-v1`
- 状态：待架构审核
- 声明：以下公式、权重和阈值均为原创虚构演示值，不来源于真实评分卡、银行参数或前雇主策略。

## 1. 演示评分公式

评分范围 0–1000，分数越高表示较低的演示风险。分数不是违约概率，不具有真实预测效力，不报告 AUC、KS、准确率或任何真实风险效果。

使用从十进制字符串构造的 Decimal 精确运算。唯一执行顺序是：校验全部输入 → 计算未舍入派生比率 → 计算六项原始贡献 → 将每项贡献分别 clamp 到 `[0, 该项最大贡献]` → 对每项使用 `ROUND_HALF_UP` 取整为整数 → 六项整数求和 → 校验总分位于 0–1000。总分不得再次取整，最终 clamp 仅作为不变量保护，正常公式不会触发。

```text
E = 150 × min(employment_months / 120, 1)
H = 150 × min(credit_history_months / 240, 1)
D = 250 × (1 - min(monthly_debt_payment / monthly_income, 1))
L = 200 × max(0, 1 - delinquency_count_12m / 5)
Q = 100 × max(0, 1 - inquiry_count_6m / 10)
A = 150 × (1 - min(requested_amount / (12 × monthly_income), 1))

score = clamp(round_half_up(E) + round_half_up(H) + round_half_up(D)
              + round_half_up(L) + round_half_up(Q) + round_half_up(A), 0, 1000)
```

六项最大贡献之和为 `150+150+250+200+100+150=1000`。由于每项在取整前单独限幅，任何 `rounded_contribution` 都必须位于 0 与其最大贡献之间；`score` 必须严格等于六项整数贡献之和，否则返回 `SCORE_INVARIANT_VIOLATION`，不得通过调整总分掩盖错误。

| 因素 ID | 含义 | 最大贡献 | 对分数方向 | 证据字段 |
|---|---|---:|---|---|
| `F_EMPLOYMENT` | 合成就业持续月数 | 150 | 月数增加不降低分数，120 月封顶 | `/employment_months` |
| `F_HISTORY` | 合成历史长度 | 150 | 月数增加不降低分数，240 月封顶 | `/credit_history_months` |
| `F_DEBT_LOAD` | 月度债务负担 | 250 | 比率增加不提高分数，1.0 后为 0 | `/monthly_debt_payment`、`/monthly_income` |
| `F_DELINQUENCY` | 12 月演示逾期次数 | 200 | 次数增加不提高分数，5 次后为 0 | `/delinquency_count_12m` |
| `F_INQUIRY` | 6 月演示查询次数 | 100 | 次数增加不提高分数，10 次后为 0 | `/inquiry_count_6m` |
| `F_AFFORDABILITY` | 申请额/合成年收入 | 150 | 比率增加不提高分数，1.0 后为 0 | `/requested_amount`、`/monthly_income` |

Model Risk Factor 输出每项限幅后的 `raw_contribution` 规范化十进制字符串、`rounded_contribution`、最大贡献、方向、公式 ID 和 evidence IDs。自然语言只能说明贡献方向与证据值，例如“较高负担使 F_DEBT_LOAD 贡献较低”，不得把低贡献表述为实际违约概率或自动称为拒绝原因。

## 2. 风险等级

| 分数区间 | 演示等级 | 边界规则 |
|---|---|---|
| 750–1000 | LOW | 750 属于 LOW |
| 500–749 | MEDIUM | 500 属于 MEDIUM，749 属于 MEDIUM |
| 0–499 | HIGH | 499 属于 HIGH |

等级只描述演示分数区间，不等同于策略结果。LOW 仍可能因规则命中而 `REJECT`；HIGH 只有在策略阈值规则生效且全部依赖有效时才形成对应 Policy Decision Reason。

## 3. 手工可复核示例

以下仅是公式样例，不指定未来数据集中的客户编号。

| 示例 | income | debt | emp | history | delinquency | inquiry | request | E/H/D/L/Q/A | 总分 | 等级 |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|
| S1 | 10,000 | 2,000 | 120 | 240 | 0 | 0 | 12,000 | 150/150/200/200/100/135 | 935 | LOW |
| S2 | 5,000 | 2,500 | 60 | 120 | 1 | 2 | 30,000 | 75/75/125/160/80/75 | 590 | MEDIUM |
| S3 | 4,000 | 4,000 | 0 | 0 | 5 | 10 | 48,000 | 0/0/0/0/0/0 | 0 | HIGH |
| S4 | 5,000 | 2,000 | 120 | 240 | 1 | 2 | 36,000 | 150/150/150/160/80/60 | 750 | LOW |
| S5 | 5,000 | 2,500 | 60 | 120 | 2 | 4 | 42,400 | 75/75/125/120/60/44 | 499 | HIGH |

复核 S5：申请额比率为 `42400 / 60000 = 0.706666…`，A 为 `150 × 0.293333… = 44`；总分 `75+75+125+120+60+44=499`。S4 和 S5 分别冻结 750/499 等级边界；实现测试还必须覆盖 500 和 749。

## 4. 模拟规则

规则按 `R001` 至 `R004` 顺序执行，但全部规则都必须记录命中与未命中；前一规则命中不短路后续记录。

| rule_id | rule_version | field/派生字段 | operator | threshold | 命中 result | evidence_ref |
|---|---|---|---|---|---|---|
| `R001` | `demo-rules-v1` | `verified_identity` | `==` | `false` | `REJECT_CANDIDATE` | `/verified_identity` |
| `R002` | `demo-rules-v1` | `delinquency_count_12m` | `>=` | `3` | `REJECT_CANDIDATE` | `/delinquency_count_12m` |
| `R003` | `demo-rules-v1` | `debt_to_income_ratio` | `>=` | `0.80` | `REJECT_CANDIDATE` | `/monthly_debt_payment`、`/monthly_income` |
| `R004` | `demo-rules-v1` | `request_to_annual_income_ratio` | `>` | `1.00` | `REJECT_CANDIDATE` | `/requested_amount`、`/monthly_income` |

边界语义固定：R002 在 3 命中；R003 在 0.80 命中；R004 在 1.00 不命中、严格大于 1.00 才命中。布尔比较不做真值字符串转换。所有比率用未舍入 Decimal 比较。

每条 RuleExecution 记录 `rule_id`、版本、顺序、字段路径、操作符、规范化阈值、规范化实际值、`matched`、result 和 evidence IDs。未命中时 `result=NO_ACTION`，仍必须保留记录。

## 5. 决策策略

DecisionTool 的必需输入：

- 完整 RuleEngineTool 结果，状态成功且阶段 A 证据为 `CONSISTENT`；
- 完整 RiskModelTool 结果，状态成功且阶段 A 证据为 `CONSISTENT`；
- `strategy_version=demo-policy-v1`；
- 客户、数据、规则、模型和策略版本关联一致。

决策顺序：

1. 任一必需输入缺失、失败、过期或不一致：不得运行或发布确定性结果；已进入评估时 `NEEDS_REVIEW`，否则 `NOT_EVALUATED`。
2. 任一 R001–R004 命中：`REJECT`；每条命中规则产生独立 Policy Decision Reason。
3. 否则若演示分数 `<500`：命中 DecisionTool 独立策略条件 `P_SCORE_001` 并得到 `REJECT`。`P_SCORE_001` 不是第五条 RuleEngineTool 规则，不改变 `matched_rule_count`，也不得伪造 R001–R004 命中。该条件引用已验证总分证据，不把任何 Model Risk Factor 改称拒绝原因。
4. 否则：`PASS`，表示“未触发模拟拒绝规则”；Policy Decision Reason 为空。

分数恰好 500 不触发 `P_SCORE_001`，499 触发。只有 R001–R004 均未命中且 score≥500 时才允许 PASS。若规则命中且分数也低于 500，输出所有规则原因及 `P_SCORE_001`，顺序为规则 ID 后评分策略原因。

## 6. 原因与固定业务指引

| 条件 | Policy Decision Reason ID | Business Guidance 模板 ID |
|---|---|---|
| R001 | `P_R001_IDENTITY_UNVERIFIED` | `BG_REVIEW_REQUIRED_DATA` |
| R002 | `P_R002_DELINQUENCY_THRESHOLD` | `BG_REVIEW_RULE_EVIDENCE` |
| R003 | `P_R003_DEBT_RATIO_THRESHOLD` | `BG_REVIEW_RULE_EVIDENCE` |
| R004 | `P_R004_REQUEST_RATIO_THRESHOLD` | `BG_REVIEW_RULE_EVIDENCE` |
| score < 500 | `P_SCORE_001` | `BG_REVIEW_SCORE_EVIDENCE` |
| PASS | 无 | `BG_NO_REJECT_RULE` |
| 依赖失败/冲突 | 无确定性原因 | `BG_MANUAL_REVIEW_REQUIRED` |

模板内容由实现以常量冻结并测试；LLM 只能在非实质性外围表达中引用模板原文，不能改变建议含义。

## 7. 可复现性与安全

- 模型、规则和策略版本必须出现在响应及证据中。
- 禁止浮点二进制比较；使用从十进制字符串构造的 Decimal。
- 禁止隐式缺失值填充、时间依赖、随机分支或 LLM 参与计算。
- 所有阈值为本项目原创演示设计，不得宣传真实预测能力。
- 评分测试、规则边界与策略组合见 [测试设计](test_design_v01.md)。

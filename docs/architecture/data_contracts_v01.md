# CreditPilot V0.1 合成数据契约

- 契约版本：`customer-schema-v1`
- 数据版本：`synthetic-v1`
- 状态：待架构审核
- 原则：仅定义原创合成演示字段，本轮不生成实际数据文件。

## 1. 数据边界

数据不得来源于真实客户、真实征信、真实银行接口、真实策略资料或前雇主材料。字段名称和范围仅服务 V0.1 演示公式与规则，不表示真实机构采集标准。

客户 ID 必须匹配 `^DEMO-[0-9]{4}$`；V0.1 生成范围建议为 `DEMO-0001` 至 `DEMO-0030`，但具体记录结果由 CP-03 根据本契约生成，不由示例编号暗示。

## 2. 数据集元数据

| 字段 | 类型 | 固定/范围 | 必需 | 用途 |
|---|---|---|---|---|
| `data_version` | string | `synthetic-v1` | 是 | 每条记录及数据集清单的版本关联 |
| `schema_version` | string | `customer-schema-v1` | 是 | schema 兼容性校验 |
| `generator_seed` | integer | `202501` | 是 | 数据集级伪随机种子 |
| `record_count` | integer | `>=30` | 是 | 清单记录数 |

生成器必须使用本地确定性 PRNG，并记录 `generator_seed=202501`。相同生成器版本、种子和记录数必须产生字节级等价的规范化数据。不得使用当前时间、网络数据或机器相关熵。

## 3. 客户字段

必需性分类：`SCORE` 为评分必需，`POLICY` 为规则/策略必需，`DISPLAY` 仅展示。一个字段可属于多个分类。任何 SCORE 或 POLICY 字段缺失、为 null、超范围或类型错误，完整分析不得输出最终 `PASS` / `REJECT`。

| 字段 | 类型 | 范围/枚举 | 单位 | 分类 | 缺失策略 |
|---|---|---|---|---|---|
| `customer_id` | string | `^DEMO-[0-9]{4}$` | 无 | SCORE、POLICY | 无效为 `INVALID_INPUT`；合法但不存在为 `NOT_FOUND` |
| `data_version` | string | `synthetic-v1` | 无 | SCORE、POLICY | 阻断计算，`DATA_VERSION_MISMATCH` |
| `verified_identity` | boolean | `true/false` | 无 | POLICY | 阻断策略，`REQUIRED_FIELD_MISSING` |
| `monthly_income` | integer | 1,000–100,000 | 合成货币单位/月 | SCORE、POLICY | 阻断评分和策略；禁止补值 |
| `monthly_debt_payment` | integer | 0–100,000 | 合成货币单位/月 | SCORE、POLICY | 阻断评分和策略；禁止补值 |
| `employment_months` | integer | 0–600 | 月 | SCORE | 阻断评分；禁止补值 |
| `credit_history_months` | integer | 0–600 | 月 | SCORE | 阻断评分；禁止补值 |
| `delinquency_count_12m` | integer | 0–12 | 次/12 月 | SCORE、POLICY | 阻断评分和规则；禁止补值 |
| `inquiry_count_6m` | integer | 0–20 | 次/6 月 | SCORE | 阻断评分；禁止补值 |
| `requested_amount` | integer | 1,000–500,000 | 合成货币单位 | SCORE、POLICY | 阻断评分和策略；禁止补值 |
| `synthetic_region` | string/null | `SYN-NORTH`、`SYN-SOUTH`、`SYN-EAST`、`SYN-WEST` | 无 | DISPLAY | 可为 null；显示“未提供”，不影响计算 |
| `scenario_label` | string/null | 最长 40 字符的合成标签 | 无 | DISPLAY | 可为 null；不推断，不影响计算 |

所有数值必须是 JSON integer，禁止 NaN、Infinity、负零和字符串数字。金额不对应任何真实币种。V0.1 不保存姓名、证件号、电话、地址、真实雇主或自由文本客户备注。

### 3.1 字段—评分—规则—策略依赖矩阵

| 字段 | 评分因素 | RuleEngine 条件 | DecisionTool 依赖 | 缺失/无效处理 |
|---|---|---|---|---|
| `customer_id` | 元数据关联 | 所有执行记录关联 | 所有原因与证据关联 | 格式非法 INVALID_INPUT；不存在 NOT_FOUND |
| `data_version` | 模型证据版本 | 规则证据版本 | 阶段 A 版本一致性 | 不匹配时阻断全部计算 |
| `verified_identity` | 无 | R001 | 通过 R001 结果 | 阻断规则与最终策略 |
| `monthly_income` | F_DEBT_LOAD、F_AFFORDABILITY | R003、R004 的分母 | 通过规则及分数结果 | null、≤0、超范围均为契约错误，停止必需计算 |
| `monthly_debt_payment` | F_DEBT_LOAD | R003 分子 | 通过规则及分数结果 | null、负数、超范围均停止必需计算 |
| `employment_months` | F_EMPLOYMENT | 无 | 通过完整评分结果 | null、负数、超范围均停止评分和最终策略 |
| `credit_history_months` | F_HISTORY | 无 | 通过完整评分结果 | null、负数、超范围均停止评分和最终策略 |
| `delinquency_count_12m` | F_DELINQUENCY | R002 | 通过规则及分数结果 | null、负数、超范围均停止必需计算 |
| `inquiry_count_6m` | F_INQUIRY | 无 | 通过完整评分结果 | null、负数、超范围均停止评分和最终策略 |
| `requested_amount` | F_AFFORDABILITY | R004 分子 | 通过规则及分数结果 | null、≤0、超范围均停止必需计算 |
| `synthetic_region` | 无 | 无 | 无 | 可缺失，不改变任何计算 |
| `scenario_label` | 无 | 无 | 无 | 可缺失，不改变任何计算 |

12 个客户字段中，8 个业务数值/布尔字段覆盖全部六项评分因素和四条规则；customer_id 与 data_version 提供强制关联，两个 DISPLAY 字段不参与计算。任何公式或规则不得读取矩阵外字段。

## 4. 派生字段

派生字段不写回源记录，由工具以精确公式计算并附证据：

| 字段 | 公式 | 范围 | 精度 |
|---|---|---|---|
| `debt_to_income_ratio` | `monthly_debt_payment / monthly_income` | `>=0` | Decimal，不提前舍入 |
| `request_to_annual_income_ratio` | `requested_amount / (12 * monthly_income)` | `>0` | Decimal，不提前舍入 |

分母字段已限定大于零。比较规则使用未舍入 Decimal 值；仅展示层可格式化为小数点后四位，展示值不得反向参与计算。

`monthly_income=0`、负数、null 或字符串均不进入除法：CustomerTool/schema 校验先返回 `DATA_CONTRACT_VIOLATION`，RiskModelTool 与 RuleEngineTool 不执行依赖计算，DecisionTool 不得调用。其他必需数值的负数、null 和越界值采用同一 fail-closed 原则。

## 5. 缺失与无效数据处理

| 情况 | analysis_status | decision_status | 错误码 |
|---|---|---|---|
| 客户 ID 格式非法 | INVALID_INPUT | NOT_EVALUATED | `INVALID_CUSTOMER_ID` |
| 合法 ID 不存在 | NOT_FOUND | NOT_EVALUATED | `CUSTOMER_NOT_FOUND` |
| SCORE/POLICY 字段缺失 | PARTIAL | NEEDS_REVIEW 或 NOT_EVALUATED | `REQUIRED_FIELD_MISSING` |
| 必需字段类型/范围非法 | FAILED | NOT_EVALUATED | `DATA_CONTRACT_VIOLATION` |
| DISPLAY 字段缺失 | 计算状态不变 | 计算状态不变 | 可选 `OPTIONAL_FIELD_MISSING` warning |
| 数据版本不符 | FAILED | NOT_EVALUATED | `DATA_VERSION_MISMATCH` |

若 CustomerTool 已成功确认客户但在计算准备阶段发现必需字段缺失，使用 `PARTIAL/NEEDS_REVIEW`；若记录无法通过 schema 构造，使用 `FAILED/NOT_EVALUATED`。

## 6. 至少 30 条记录的生成原则

CP-03 应生成不少于 30 条记录，并满足：

1. ID 连续、唯一，排序稳定；不将特定结果永久绑定到 `DEMO-0001/0002` 的语义描述。
2. 至少 6 条不命中拒绝规则且分数不低于 500。
3. 每条规则至少有 3 条独立命中记录，并至少有 1 条只命中该规则。
4. 至少覆盖一个多规则同时命中场景。
5. 每个风险等级至少 5 条完整记录。
6. 对每个数值规则创建阈值下、阈值等于、阈值上至少各 1 条边界记录；记录可复用。
7. 另建测试专用无效/缺失夹具，不混入正式 30 条有效数据集。
8. DISPLAY 字段至少包含有值和 null 两类，以验证其不影响评分与策略。
9. 分布不用于真实统计推断，不标注真实通过率、坏账率或代表性。
10. 生成后输出清单哈希；源字段值与预期规则/分数由测试独立复算。

## 7. 规范化与完整性

- JSON 编码 UTF-8，键顺序采用 schema 顺序，换行符固定为 LF。
- 每个客户对象禁止额外字段，避免悄然引入未审核信息。
- 数据集不得包含预计算最终决策；测试期望值放在独立冻结夹具中。
- 数据证据 `field_path` 采用 JSON Pointer，例如 `/monthly_income`。
- CustomerTool 返回记录内容的不可变快照和 `data_version`，下游不得修改。

## 8. 追踪与链接

本契约支持 FR-01、FR-03、FR-04、FR-06、FR-07，以及 AC-004、006、007、008、010、011。评分与规则对字段的具体使用见 [评分与模拟策略](risk_policy_v01.md)，工具 schema 见 [工具契约](tool_contracts_v01.md)。

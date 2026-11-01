# CreditPilot V0.1 工具、状态、证据与 API 契约

- 契约版本：`tool-contracts-v1`
- 状态：待架构审核
- 说明：本文是设计契约，不表示工具或端点已经实现。

## 1. 通用原则

- 所有工具只读或纯计算，不执行审批、授信、额度、通知或任何真实业务写操作。
- 工具输入输出后续使用 Pydantic 严格模型并禁止额外字段。
- 每次调用携带 `request_id`（UUID）和明确版本；相同输入与版本产生相同规范化输出。
- 错误作为结构化结果返回给编排器，禁止用技术异常表示模拟拒绝。
- 只有 EvidenceValidator 阶段 A 通过后，DecisionTool 才可被调用。

## 2. 通用 schema

### ToolError

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `code` | ErrorCode | 是 | 稳定机器码 |
| `message` | string | 是 | 安全、非敏感摘要 |
| `source_tool` | string | 是 | 失败工具 |
| `retryable` | boolean | 是 | 仅表示技术上是否可重试 |
| `details` | map/null | 否 | 白名单详情，如缺失字段；不含完整画像或秘密 |

### ToolResultEnvelope

| 字段 | 类型 | 说明 |
|---|---|---|
| `request_id` | UUID | 请求关联 ID |
| `tool_name` | enum | 白名单工具名 |
| `tool_version` | string | 工具实现契约版本 |
| `success` | boolean | 技术/契约执行是否成功 |
| `payload` | tool-specific/null | 成功载荷 |
| `evidence` | list[Evidence] | 可为部分已验证证据 |
| `errors` | list[ToolError] | 失败或 warning |

## 3. CustomerTool

- 职责：按合法 ID 从 `synthetic-v1` 本地数据集中精确读取不可变客户快照。
- 输入 schema：`request_id`、`customer_id`、`expected_data_version`。
- 输出 schema：`CustomerSnapshot`（[数据字段](data_contracts_v01.md#3-客户字段)）、`missing_required_fields[]`、`missing_optional_fields[]`、客户字段 Evidence。
- 依赖：本地只读合成数据文件和数据清单。
- 前置条件：customer_id 已通过格式校验。
- 异常：不存在、版本不符、记录 schema 无效、只读文件不可用。
- 错误码：`CUSTOMER_NOT_FOUND`、`DATA_VERSION_MISMATCH`、`DATA_CONTRACT_VIOLATION`、`TOOL_UNAVAILABLE`。
- 证据字段：每个返回源字段至少包含 customer_id、data_version、field_path、value、source_tool。
- 版本字段：data_version、schema_version、tool_version。
- 可复现性：相同 ID 和 data_version 返回相同规范化快照；禁止模糊匹配或生成记录。
- 追踪：FR-01、FR-07；AC-001、002、006、007、011。

## 4. RuleEngineTool

- 职责：按固定顺序执行 R001–R004，记录每条命中与未命中结果。
- 输入 schema：`request_id`、`CustomerSnapshot`、`rule_version=demo-rules-v1`。
- 输出 schema：`rule_version`、`total_rule_count=4`、`matched_rule_count`、`executions[]`、Evidence。
- `RuleExecution`：rule_id、rule_version、sequence、field_paths[]、operator、threshold、actual_value、matched、result、evidence_ids[]。
- 依赖：有效客户快照与冻结规则定义。
- 前置条件：全部 POLICY 字段存在且类型/范围有效。
- 异常：字段缺失、版本未知、派生比率失败、规则定义无效。
- 错误码：`REQUIRED_FIELD_MISSING`、`RULE_VERSION_UNSUPPORTED`、`RULE_EXECUTION_FAILED`、`DATA_CONTRACT_VIOLATION`。
- 证据字段：源字段 Evidence 加每个 RuleExecution 的派生 Evidence；不得只为命中规则留证据。
- 版本字段：data_version、rule_version、tool_version。
- 可复现性：Decimal 精确比较；不短路；相同快照和版本结果完全一致。
- 追踪：FR-02；AC-001、002、003、007、008、009、010。

## 5. RiskModelTool

- 职责：执行 `demo-score-v1` 六项透明公式，输出分数、等级和 Model Risk Factors。
- 输入 schema：`request_id`、`CustomerSnapshot`、`model_version=demo-score-v1`。
- 输出 schema：`score` integer、`risk_level` enum、`factors[6]`、`model_version`、Evidence。
- `ModelRiskFactor`：factor_id、raw_contribution decimal-string、rounded_contribution integer、max_contribution、direction、formula_id、evidence_ids[]。
- 依赖：有效客户快照与冻结公式。
- 前置条件：全部 SCORE 字段存在且有效。
- 异常：字段缺失、版本未知、算术/范围错误、贡献和与总分不一致。
- 错误码：`REQUIRED_FIELD_MISSING`、`MODEL_VERSION_UNSUPPORTED`、`SCORE_CALCULATION_FAILED`、`SCORE_INVARIANT_VIOLATION`。
- 证据字段：输入字段、两项派生比率、六项贡献、总分和等级均可由 evidence_id 关联。
- 版本字段：data_version、model_version、tool_version。
- 可复现性：Decimal + ROUND_HALF_UP；禁止随机、浮点或 LLM。
- 追踪：FR-03；AC-002、004、005、007、009、010。

## 6. DecisionTool

- 职责：只在已验证规则和评分结果上执行 `demo-policy-v1`。
- 输入 schema：`request_id`、`validated_rule_result`、`validated_score_result`、`strategy_version`、阶段 A ValidationReport ID。
- 输出 schema：`decision_status`、`policy_decision_reasons[]`、`business_guidance_template_id`、`strategy_version`、Evidence。
- `PolicyDecisionReason`：reason_id、reason_text_key、source_type (`RULE`/`SCORE_POLICY`)、source_id、strategy_version、evidence_ids[]。
- 依赖：RuleEngineTool 与 RiskModelTool 均成功；阶段 A `CONSISTENT`；版本关系有效。
- 前置条件：不得接受原始客户快照替代经验证工具结果。
- 异常：依赖无效、证据报告缺失、版本不符、策略不变量失败。
- 错误码：`DEPENDENCY_NOT_VALIDATED`、`EVIDENCE_INCONSISTENT`、`STRATEGY_VERSION_UNSUPPORTED`、`DECISION_INVARIANT_VIOLATION`。
- 证据字段：每个原因引用规则执行或总分证据；PASS 不生成虚构原因。
- 版本字段：data_version、rule_version、model_version、strategy_version、tool_version。
- 可复现性：固定优先顺序和原因排序；无随机或 LLM。
- 追踪：FR-04；AC-001、002、003、005、007、008、009、010。

评分门槛使用 `source_type=SCORE_POLICY`、`source_id=P_SCORE_001`，引用 RiskModelTool 的总分及 model_version 证据。它不是 RuleExecution，不计入规则总数或命中数。规则原因只能引用实际 `matched=true` 的 R001–R004；DecisionTool 不得为评分门槛伪造规则执行记录。

## 7. EvidenceValidator

- 职责：阶段 A 校验工具证据，阶段 B 校验最终解释；自身纯计算且不能修复证据。
- 输入 schema（A）：customer snapshot、rule result、score result、全部 Evidence、expected version set。
- 输出 schema（A）：`ValidationReport`，含 report_id、stage=`TOOL_OUTPUT`、status、issues[]、validated_evidence_ids[]、blocked_conclusions[]。
- 输入 schema（B）：已验证结构化结果、候选解释、解释引用的 evidence_ids。
- 输出 schema（B）：stage=`FINAL_EXPLANATION` 的 ValidationReport、可发布解释或阻断字段。
- 依赖：规范化工具结果；阶段 B 还依赖确定性决策。
- 前置条件：阶段和期望版本明确。
- 异常：缺失、冲突、过期、来源错误、无效引用、解释包含无证据数值/结论。
- 错误码：`EVIDENCE_MISSING`、`EVIDENCE_CONFLICT`、`EVIDENCE_STALE`、`EVIDENCE_SOURCE_INVALID`、`EXPLANATION_UNSUPPORTED`。
- 版本字段：validator_version；按证据类型校验适用版本。
- 可复现性：相同结构化输入产生相同 issues 排序与 status。
- 追踪：FR-06；AC-003、005、007、010、013。

阶段 A 的最小检查集为：customer_id、data_version、rule_version、model_version、源字段值、派生比率、四条规则结果、六项评分贡献、总分、等级及各引用关系。阶段 B 的最小检查集为：候选解释中的分数、等级、规则命中、Policy Decision Reason ID（含 `P_SCORE_001`）、因素贡献、全部版本及 evidence_id。LLM 不得增加、修改、删除或重新分类任何事实性结论；Validator 发现问题时只标记并阻断，不自行修复。

## 8. 证据契约

### Evidence

| 字段 | 类型 | 必需性/规则 |
|---|---|---|
| `evidence_id` | string | 必需；建议 `EV-{source}-{stable_hash_prefix}`，同输入稳定 |
| `source_tool` | enum | 必需；必须为实际生产该证据的白名单工具 |
| `customer_id` | string | 必需 |
| `data_version` | string | 必需 |
| `rule_version` | string/null | 规则执行与规则派生证据必需；其他可 null |
| `model_version` | string/null | 分数、因素和等级证据必需；其他可 null |
| `strategy_version` | string/null | 决策与原因证据必需；其他可 null |
| `field_path` | JSON Pointer | 必需；派生字段使用 `/derived/...`，结论使用 `/result/...` |
| `value` | JSON scalar/object | 必需；采用规范化值，Decimal 用字符串 |
| `validation_status` | EvidenceStatus | 必需 |

EvidenceStatus 冻结为：`PENDING`、`VALID`、`MISSING`、`CONFLICT`、`STALE`、`INVALID_SOURCE`。工具初始输出为 PENDING；只有 EvidenceValidator 可产生其余校验状态。版本字段按来源适用，不得伪造不适用版本：客户源字段只需 data_version；规则证据关联 rule_version；评分证据关联 model_version；决策证据必须同时关联 rule/model/strategy 版本。

### 阶段 A 失败策略

| 问题 | EvidenceStatus | 处理 |
|---|---|---|
| 必需 evidence_id/字段缺失 | MISSING | 阻断相关工具结果；禁止 DecisionTool |
| 同一 field_path 在同版本出现不同值 | CONFLICT | 阻断所有受影响结论；NEEDS_REVIEW |
| data/tool 版本不等于请求期望 | STALE | 阻断结果；不得回退使用旧版本 |
| source_tool 与字段类型不匹配 | INVALID_SOURCE | 阻断引用与下游决策 |

### 阶段 B 失败策略

解释中的数值、状态、原因和因素必须引用 VALID evidence_id。出现无引用主张、引用值不一致或把 Model Risk Factor 写成 Policy Decision Reason 时，标记 `EXPLANATION_UNSUPPORTED`，不展示受影响解释。已通过阶段 A 和 DecisionTool 的结构化决策可保留，整体 `analysis_status=PARTIAL`。

## 9. 状态契约

### 允许组合

| analysis_status | 允许的 decision_status | 含义 |
|---|---|---|
| SUCCESS | PASS、REJECT、NOT_EVALUATED | 完整决策成功，或用户只请求无需策略的独立分析 |
| PARTIAL | NEEDS_REVIEW、NOT_EVALUATED | 部分证据有效，但决策依赖不完整/未开始 |
| PARTIAL | PASS、REJECT | 仅允许确定性决策已完成且阶段 A 有效，而可选 LLM/阶段 B 表达失败 |
| FAILED | NOT_EVALUATED | 无可发布分析且未形成决策 |
| NOT_FOUND | NOT_EVALUATED | 合法客户不存在 |
| INVALID_INPUT | NOT_EVALUATED | 请求未通过校验 |

禁止组合包括：FAILED/NOT_FOUND/INVALID_INPUT 与 PASS 或 REJECT、SUCCESS 与 NEEDS_REVIEW、任何必需规则/评分依赖失败时的 PASS 或 REJECT。技术失败不产生 REJECT。

### 统一错误码

| 类别 | 错误码 |
|---|---|
| 输入/客户 | `INVALID_CUSTOMER_ID`、`INVALID_QUESTION`、`INVALID_MODE`、`CUSTOMER_NOT_FOUND` |
| 数据 | `REQUIRED_FIELD_MISSING`、`DATA_CONTRACT_VIOLATION`、`DATA_VERSION_MISMATCH` |
| 规则 | `RULE_VERSION_UNSUPPORTED`、`RULE_EXECUTION_FAILED` |
| 评分 | `MODEL_VERSION_UNSUPPORTED`、`SCORE_CALCULATION_FAILED`、`SCORE_INVARIANT_VIOLATION` |
| 决策 | `DEPENDENCY_NOT_VALIDATED`、`STRATEGY_VERSION_UNSUPPORTED`、`DECISION_INVARIANT_VIOLATION` |
| 证据 | `EVIDENCE_MISSING`、`EVIDENCE_CONFLICT`、`EVIDENCE_STALE`、`EVIDENCE_SOURCE_INVALID`、`EXPLANATION_UNSUPPORTED` |
| 工具/LLM | `TOOL_UNAVAILABLE`、`TOOL_TIMEOUT`、`LLM_UNAVAILABLE`、`LLM_TIMEOUT`、`LLM_OUTPUT_INVALID` |
| 安全 | `UNSUPPORTED_INTENT`、`PROMPT_INJECTION_REJECTED`、`UNAUTHORIZED_OPERATION` |

错误码可多值并按工具执行顺序排序。不得在 message 中回显恶意输入、密钥、内部路径或完整客户画像。

### LLM 降级标记

响应 `degradation` 为 null 或对象：`active=true`、`component=LLM`、`reason_code`、`fallback=FIXED_TEMPLATE`、`deterministic_result_preserved`。LLM 是可选依赖；若阶段 A 与决策已完成，LLM 失败可保留 PASS/REJECT，但 analysis_status 为 PARTIAL。若 LLM 用于请求理解且无法安全确定意图，返回 FAILED/NOT_EVALUATED。

## 10. POST /analyze API

### 请求

```json
{
  "customer_id": "DEMO-0001",
  "question": "请解释该模拟客户的风险结果",
  "mode": "rules"
}
```

| 字段 | 约束 |
|---|---|
| `customer_id` | 必需，匹配 `^DEMO-[0-9]{4}$` |
| `question` | 必需，去除首尾空白后 1–500 字符；禁止控制字符 |
| `mode` | 必需，`rules` 或 `llm` |

`rules` 使用固定意图集合与固定解释模板，全程离线。`llm` 是可选模式，可辅助识别允许意图和组织非实质性表达，但仍执行完整确定性工具链；默认配置不发起真实调用，测试必须 Mock，CP-02 不调用真实 DeepSeek。

### 响应顶层

| 字段 | 类型 |
|---|---|
| `request_id` | UUID |
| `analysis_status` | AnalysisStatus |
| `decision_status` | DecisionStatus |
| `customer_id` | string/null |
| `versions` | data/rule/model/strategy/contract versions |
| `rule_summary` | total、matched、executions |
| `risk_score` | score、level、factors 或 null |
| `score_policy` | `condition_id=P_SCORE_001`、threshold、operator、condition_triggered、pass_threshold_met、evidence_ids；与 rule_summary 分离 |
| `policy_decision_reasons` | array，与 model factors 分离 |
| `business_guidance` | 固定模板对象 |
| `evidence` | VALID 或明确部分状态的证据列表 |
| `validation_reports` | 阶段 A/B 摘要 |
| `errors` | ToolError array |
| `degradation` | null 或降级对象 |
| `disclaimer` | 固定演示免责声明 |

Web/API 必须分别提供 `rule_summary`、`score_policy`、`risk_score` 和完整 `decision_status`，并始终带非真实授信免责声明。`condition_triggered` 表示 score<500，`pass_threshold_met` 表示 score≥500，两者必须互为相反值。PASS 的显示文案严格使用“未触发模拟拒绝规则”，但该文案不能替代 `pass_threshold_met=true` 的独立展示。

### HTTP 映射

| 条件 | HTTP | 主状态 |
|---|---:|---|
| SUCCESS | 200 | 对应决策状态 |
| PARTIAL 且有安全可展示证据 | 200 | NEEDS_REVIEW/NOT_EVALUATED，或仅可选表达失败时保留决策 |
| 客户不存在 | 404 | NOT_FOUND/NOT_EVALUATED |
| 请求 schema/客户 ID 非法 | 422 | INVALID_INPUT/NOT_EVALUATED |
| 必需内部工具失败且无可发布证据 | 503 | FAILED/NOT_EVALUATED |
| 未处理内部错误 | 500 | FAILED/NOT_EVALUATED，通用消息 |

业务上的模拟 REJECT 仍返回 HTTP 200；HTTP 4xx/5xx 不得解释为策略拒绝。

## 11. Agent 边界、超时与安全

- 白名单工具：CustomerTool、RuleEngineTool、RiskModelTool、DecisionTool、EvidenceValidator；LLM 不能增加工具。
- 允许意图：查询客户合成资料、规则、评分、策略原因、证据、三类输出差异。
- 禁止意图：真实审批/额度/通知、密钥读取、系统写入、绕过规则、改变结果、查询非合成客户。
- 设计目标超时：本地工具 2 秒；Mock LLM 5 秒。这是待实现和测试验证的控制目标，不是已验证 SLA；超时值可配置但必须有上限。
- 自动重试：确定性只读本地工具最多 1 次，仅限明确瞬态错误；LLM 默认不自动重试。重试不得改变 request_id 或版本。
- 提示注入文本是非可信输入，不能覆盖系统边界、白名单或结构化结果。
- 超时结果必须进入 `PARTIAL` 或 `FAILED` 并带 `TOOL_TIMEOUT`/`LLM_TIMEOUT`；不得将缺失载荷包装为 success。只有必需工具和阶段 A 已成功、确定性决策已验证时，可选表达层超时才允许 `PARTIAL + PASS/REJECT`。

## 12. 相关文档

- [系统架构](system_design_v01.md)
- [数据契约](data_contracts_v01.md)
- [评分与策略](risk_policy_v01.md)
- [测试设计](test_design_v01.md)

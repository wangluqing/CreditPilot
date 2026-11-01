# CreditPilot V0.1 测试设计

- 测试设计版本：`test-design-v1`
- 状态：待架构审核
- 声明：本文件定义未来测试，不声称任何业务测试已经实现或通过。

## 1. 测试原则

- 默认离线；使用冻结合成夹具和 Mock LLM，不调用真实 DeepSeek 或外部服务。
- 断言结构化值、版本、证据和状态，不以完整自然语言句子作为唯一断言。
- 规则、评分、决策和证据校验分别单测，再进行确定性集成测试。
- 测试名包含 AC ID，例如 `test_ac_008_r003_equal_threshold_matches`。
- 固定 Decimal 输入、版本和生成种子，禁止时间或随机不稳定性。

## 2. AC 与组件映射

| AC | 主要组件 | 测试层级 | 核心断言 |
|---|---|---|---|
| AC-001 正常模拟拒绝 | RuleEngine、RiskModel、Validator A、Decision | 集成/API | SUCCESS/REJECT；原因来自命中规则或分数策略；证据 VALID |
| AC-002 正常模拟通过 | 全确定性链路、Web schema | 集成/API | SUCCESS/PASS；Web 文案键对应“未触发模拟拒绝规则”；无拒绝原因 |
| AC-003 规则解释 | RuleEngine、EvidenceValidator | 单元/契约 | 四条执行记录、版本、阈值、实际值、evidence_ids 完整 |
| AC-004 评分解释 | RiskModel | 单元/API | 精确分数、等级、六项贡献和相等不变量 |
| AC-005 三类输出区分 | Decision、响应 schema | 契约/API | 三个独立字段；模型因素不进入 Policy Decision Reason |
| AC-006 客户不存在 | CustomerTool、Orchestrator | 单元/API | 404、NOT_FOUND/NOT_EVALUATED；下游零调用 |
| AC-007 必需资料缺失 | CustomerTool、Orchestrator | 参数化集成 | PARTIAL；无 PASS/REJECT；缺失字段错误明确 |
| AC-008 阈值边界 | RuleEngine、RiskModel、Decision | 参数化单元 | 阈值下/等于/上符合冻结比较符和 499/500/749/750 边界 |
| AC-009 工具失败 | 各工具、Orchestrator | 故障注入 | PARTIAL 或 FAILED；无非法最终决策；部分证据明确标注 |
| AC-010 证据不一致 | EvidenceValidator A/B | 单元/集成 | 冲突路径、INCONSISTENT；阶段 A 阻断 DecisionTool |
| AC-011 非法客户编号 | FastAPI/Pydantic | API | 422、INVALID_INPUT/NOT_EVALUATED；工具零调用 |
| AC-012 注入与越权 | Agent 边界、白名单 | 安全/Mock | 无未授权调用、无秘密、确定性结果不可改写 |
| AC-013 LLM 不可用 | Mock LLM、固定模板 | 集成/API | 明确降级；已验证决策可保留；未完成意图则 FAILED |

## 3. 评分精确值测试

| 测试 ID | 输入 | 预期 |
|---|---|---|
| SCORE-001 | risk policy S1 | 六项 `150/150/200/200/100/135`，score 935，LOW |
| SCORE-002 | S2 | `75/75/125/160/80/75`，score 590，MEDIUM |
| SCORE-003 | S3 | 全部 0，score 0，HIGH |
| SCORE-004 | S4 | score 750，LOW |
| SCORE-005 | S5 | score 499，HIGH |
| SCORE-006 | 构造 score 500 | MEDIUM，分数策略不拒绝 |
| SCORE-007 | 构造 score 749 | MEDIUM |
| SCORE-008 | 超过就业/历史封顶值 | 相应贡献仍为 150 |
| SCORE-009 | 产生 .5 的原始贡献 | `ROUND_HALF_UP` 向上取整 |
| SCORE-010 | 任一 SCORE 字段缺失 | 不计算分数；`REQUIRED_FIELD_MISSING` |
| SCORE-011 | `monthly_income` 为 0、负数、null、字符串 | schema/CustomerTool 拒绝；不执行除法、规则、评分或决策 |
| SCORE-012 | 同一输入、同一 data/model version 重复执行 | 六项原始值、整数贡献、总分和等级完全相同 |

每项同时断言 `score == sum(rounded_contribution)`、0≤score≤1000、因素 evidence IDs 可解析、相同输入重复运行输出相同。

## 4. 规则边界测试

| 测试 ID | 规则 | 输入组 | 预期 matched |
|---|---|---|---|
| RULE-001 | R001 | true / false | false / true |
| RULE-002 | R002 `>=3` | 2 / 3 / 4 | false / true / true |
| RULE-003 | R003 `>=0.80` | 0.7999 / 0.80 / 0.8001 | false / true / true |
| RULE-004 | R004 `>1.00` | 0.9999 / 1.00 / 1.0001 | false / false / true |
| RULE-005 | 全规则 | 多规则命中 | 四条记录均存在，命中原因按 rule_id 排序 |
| RULE-006 | 版本错误 | unknown version | 失败且无策略决策 |

所有测试断言实际值使用规范化 Decimal 字符串、未命中记录不丢失、total_rule_count=4。

## 5. 决策与状态组合测试

| 条件 | 预期 analysis/decision |
|---|---|
| 规则有效、评分有效、无规则命中、score≥500 | SUCCESS/PASS |
| 规则有效、评分有效、任一规则命中 | SUCCESS/REJECT |
| 无规则命中、score=499 | SUCCESS/REJECT，含 `P_SCORE_001` |
| 无规则命中、score=500 | SUCCESS/PASS |
| 规则失败或评分失败 | PARTIAL/NEEDS_REVIEW 或 FAILED/NOT_EVALUATED；禁止 PASS/REJECT |
| 阶段 A 冲突 | PARTIAL/NEEDS_REVIEW；DecisionTool 零调用 |
| 阶段 B/可选 LLM 失败且决策已验证 | PARTIAL/保留原 PASS 或 REJECT；解释降级 |
| 客户不存在 | NOT_FOUND/NOT_EVALUATED |
| 输入非法 | INVALID_INPUT/NOT_EVALUATED |

上表评分门槛原因统一为 `P_SCORE_001`：测试必须断言它属于 DecisionTool 的 `SCORE_POLICY`，引用总分证据，不出现在 RuleEngineTool executions，且不改变 total/matched rule count。无规则命中且 score≥500 才允许 PASS。

对状态枚举做笛卡尔积参数化测试：允许组合必须可构造，所有未列组合必须被响应模型或不变量校验拒绝。

## 6. 证据校验测试

- 缺失：删除必需 evidence_id，期望 MISSING、`EVIDENCE_MISSING`，阻断 DecisionTool。
- 冲突：同一 customer/version/path 注入不同值，期望 CONFLICT 和精确冲突路径。
- 过期/版本冲突：分别替换 data、rule、model、strategy version，期望 STALE 或 CONFLICT，不自动回退，阶段 A 冲突时 DecisionTool 零调用。
- 来源错误：将评分证据标记 CustomerTool，期望 INVALID_SOURCE。
- 引用错误：Policy Decision Reason 引用 Model Risk Factor evidence，阶段 B 失败。
- 无证据解释：候选解释新增不存在的数值或规则，期望 `EXPLANATION_UNSUPPORTED` 且不发布该解释。
- LLM 篡改：分别让候选解释增加、修改、删除规则命中、原因 ID、分数、等级或因素贡献，阶段 B 均失败；结构化确定性结果保持不变。
- 正常：所有 evidence IDs 唯一、可解析，阶段 A/B 报告状态一致且排序稳定。

## 7. 工具异常与 LLM Mock

对 Customer、Rule、Model、Decision、Validator 分别注入超时、受控异常、无效 schema：

- 断言错误码来源、retryable、下游调用次数和敏感字段缺失。
- Rule/Model 任一失败后 DecisionTool 零调用。
- 已验证部分证据可返回，但 validation_status 与整体 PARTIAL/FAILED 明确。
- Mock LLM 返回正常引用、超时、额外虚构字段、提示注入服从文本四类结果。
- LLM 超时且决策已完成：固定模板降级、degradation.active=true、PARTIAL、决策保留。
- LLM 在意图阶段失败且 rules 模式无法确定允许意图：FAILED/NOT_EVALUATED。
- 测试通过网络封锁或 Mock transport 断言真实外部调用为零。
- 超时是 2 秒本地工具/5 秒 Mock LLM 的设计目标测试，不宣称 SLA；任何超时 envelope 的 success 必须为 false，除非是独立的固定模板降级结果。

## 8. API 契约测试

| 类别 | 输入 | 预期 |
|---|---|---|
| 正常 rules | 合法客户、合法问题、rules | 200；响应全部顶层字段；离线调用 |
| 正常 llm | 合法请求 + Mock LLM | 200；工具链仍完整；阶段 B 通过 |
| ID 非法 | 路径/控制字符/超长 | 422；不回显危险文本；工具零调用 |
| question 非法 | 空、>500、控制字符 | 422；`INVALID_QUESTION` |
| mode 非法 | 任意其他字符串 | 422；`INVALID_MODE` |
| 客户不存在 | 合法但不存在 ID | 404；NOT_FOUND/NOT_EVALUATED |
| 必需工具不可用 | 故障注入且无证据 | 503；FAILED/NOT_EVALUATED |
| 模拟 REJECT | 完整拒绝夹具 | 200；不得错误映射为 HTTP 4xx/5xx |

增加 PASS 展示契约断言：响应同时包含规则命中数/总数、`score_policy.condition_triggered=false`、`score_policy.pass_threshold_met=true`、演示分数/等级、完整 decision_status 和固定免责声明；不得用 D01 文案替代任一结构字段。

响应 schema 测试必须验证 Policy Decision Reason、Model Risk Factor、Business Guidance 独立；PASS 的公开文案键不得为“批准”。

## 9. 数据生成与可复现测试

- 相同 `generator_seed=202501`、生成器版本和数量两次生成规范化哈希相同。
- 至少 30 条、ID 唯一且格式正确、每条通过 schema。
- 覆盖 [数据生成原则](data_contracts_v01.md#6-至少-30-条记录的生成原则) 的数量断言。
- 变更种子产生不同数据但仍满足约束；正式 V0.1 只接受冻结种子清单。
- 正式数据不含预计算决策、姓名、证件、电话、地址或自由文本秘密。

## 10. 测试层级与建议文件

| 层级 | 建议测试文件 | 覆盖 |
|---|---|---|
| 单元 | `test_customer_tool.py` | 数据查询、缺失、版本 |
| 单元 | `test_rule_engine.py` | RULE-001–006 |
| 单元 | `test_risk_model.py` | SCORE-001–010 |
| 单元 | `test_decision.py` | 策略依赖、原因排序、499/500 |
| 单元 | `test_evidence.py` | 两阶段证据状态与冲突 |
| 集成 | `test_orchestrator.py` | 完整链路、故障降级、白名单 |
| API | `test_analyze_api.py` | HTTP/Pydantic/响应契约 |
| 安全 | `test_agent_safety.py` | 注入、越权、密钥与网络零调用 |

## 11. 架构验收出口

后续实现完成时才可报告测试结果。CP-02 文档审核要求：FR-01–08 与 AC-001–013 映射完整；五个手算样例可复核；规则边界唯一；状态组合无矛盾；证据阶段 A 能阻断 DecisionTool；阶段 B 能阻断不受支持解释；真实数据和真实 LLM 调用均为零。

相关契约：[系统架构](system_design_v01.md)、[数据契约](data_contracts_v01.md)、[评分策略](risk_policy_v01.md)、[工具与 API](tool_contracts_v01.md)。

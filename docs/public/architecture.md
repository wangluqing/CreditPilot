# CreditPilot V0.1 公开架构说明

本文描述当前仓库已经实现的本地演示架构，不扩展冻结需求，也不把设计目标表述为生产能力。

## 组件与数据流

```mermaid
flowchart TD
    B[Browser / Native Web] -->|same-origin POST /analyze| F[FastAPI]
    F --> O[AnalysisOrchestrator]
    O --> C[CustomerTool]
    C -->|trusted synthetic snapshot| R[RuleEngineTool]
    C -->|trusted synthetic snapshot| M[RiskModelTool]
    C --> EA[EvidenceValidator Stage A]
    R --> EA
    M --> EA
    EA -->|CONSISTENT original report| D[DecisionTool]
    D --> T[FixedTemplateEngine]
    T --> EB[EvidenceValidator Stage B]
    EB -->|validated explanation or null| O
    O --> F

    L[Optional LLM] -. not enabled in V0.1 .-> O
```

执行顺序由 `AnalysisOrchestrator` 固定。请求方只能提交 `customer_id`、`question` 和 `mode`，不能选择工具、提交证据校验报告或注入决策。

## 已实现组件

### CustomerTool

从版本化 JSON 数据集精确匹配 `DEMO-0001` 格式的客户编号。它使用严格 Pydantic 模型校验字段，不模糊搜索、不补造客户、不把非法数值自动补零。默认数据为 30 条原创合成记录，`data_version=synthetic-v1`，生成种子为 `202501`。

### RuleEngineTool

执行冻结的 `demo-rules-v1` 四条规则。四条规则全部执行且不短路，每条都记录实际值、比较符、阈值、命中状态及证据 ID。派生比率使用 Decimal 计算。

### RiskModelTool

按 `demo-score-v1` 透明公式计算六项整数贡献，贡献之和严格等于 0–1000 总分。等级为 HIGH（0–499）、MEDIUM（500–749）、LOW（750–1000）；高分只表示较低的**演示风险**，不表示违约概率。

### EvidenceValidator 阶段 A

阶段 A 把 CustomerTool 返回的客户快照作为可信重算输入，并复用现有 RuleEngineTool 与 RiskModelTool 进行独立确定性验证。它核对客户与数据版本、规则/模型版本、四条规则、六项贡献、总分、等级、证据唯一性和引用关系。Validator 只校验，不修复冲突。

这一步能够识别“同时篡改贡献、总分、等级和引用”或“同步篡改 matched 与证据”的表面自洽攻击。未通过时不会授权确定性策略决策。

### DecisionTool

只接受阶段 A 实际签发并绑定当前结果的原始 `ValidationReport`：任一 R001–R004 命中则模拟 `REJECT`；否则 `score < 500` 由独立条件 `P_SCORE_001` 产生模拟 `REJECT`；无规则命中且 `score >= 500` 才产生模拟 `PASS`。技术失败不会被映射成业务拒绝。

### 固定模板解释与阶段 B

`FixedTemplateEngine` 只从已验证结构化事实渲染中文解释和固定 Business Guidance。阶段 B 核对客户、版本、分数、等级、六项贡献、规则命中、策略原因和证据引用；失败时保留已验证决策，但响应降为 `PARTIAL` 且 `explanation=null`。

阶段 B 验证的是白名单模板及结构化事实槽位，不是对任意自由文本的通用语义证明。

### FastAPI 与 Web

FastAPI 提供 `GET /health`、`POST /analyze` 和 `/`。Web 使用同源原生 HTML/CSS/JavaScript，不加载 CDN、字体或跟踪脚本；不可信文本使用 `textContent` 等 DOM API 渲染。页面可展示结果、完整规则、三类输出、证据、版本、双阶段校验摘要及原始 JSON。

## 确定性边界与可选 LLM

客户查询、规则、评分、证据校验、模拟决策和固定模板均为确定性 Python。当前 `llm` 模式明确返回 `LLM_UNAVAILABLE`，没有真实 DeepSeek 或其他 LLM 调用。未来即使启用 LLM，它也不得跳过工具、计算评分或改变事实性结论。

## ValidationReport 授权边界

当前 DecisionTool 使用进程内对象身份、签发登记和结果绑定来阻止复制、重建、反序列化或修改报告后绕过 Validator。该机制适合单进程本地演示，但不是：

- 跨进程或跨主机认证；
- 密码学签名、远程证明或长期凭证；
- 多 worker 共享的授权存储。

如未来引入分布式部署，必须重新设计跨边界的完整性与授权机制，不能沿用本地对象身份作为安全保证。


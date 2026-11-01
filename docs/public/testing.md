# CreditPilot V0.1 测试与工程证据

## 本轮执行命令

```powershell
uv run pytest -q
uv run ruff check .
git diff --check
```

本文件中的本轮结果只记录 CP-05A 实际执行输出，不以历史 `137 passed` 替代。最终结果见“本轮实测结果”。

## pytest 覆盖范围

- 合成数据：30 条记录、严格字段类型、ID 唯一性、固定种子复现、缺失/非法字段安全失败
- CustomerTool：精确查询、NOT_FOUND、INVALID_INPUT、版本与字段可用性证据
- RuleEngineTool：R001–R004 命中/未命中、全部执行、不短路、Decimal 边界
- RiskModelTool：六项贡献、总分不变量、等级和同版本复现
- EvidenceValidator A：重算、版本/引用/唯一性、协同评分与规则篡改阻断
- DecisionTool：PASS、规则拒绝、P_SCORE_001、原因与模型因素分离
- EvidenceValidator B：解释事实槽位和引用篡改阻断，失败时隐藏候选解释
- API：HTTP/业务状态映射、输入契约、禁用 LLM、调用方不能注入报告或决策
- Web：根路由、静态资源、状态映射、阶段 B 展示门禁、安全 DOM API 与无外部资源

## 规则边界

自动化测试覆盖：R001 布尔反向；R002 `>= 3` 的 2/3/4；R003 `>= 0.80` 的下方/等值/上方；R004 `> 1.00` 的下方/等值/上方。每次仍返回全部四条执行记录。

## 评分边界与 S1–S5

测试验证 499/500/749/750 的 HIGH/MEDIUM/LOW 边界，以及 `ROUND_HALF_UP`、单项限幅、六项整数贡献之和等于总分。冻结手算样例为：

| 样例 | 六项贡献 | 总分 | 等级 |
|---|---|---:|---|
| S1 | 150/150/200/200/100/135 | 935 | LOW |
| S2 | 75/75/125/160/80/75 | 590 | MEDIUM |
| S3 | 0/0/0/0/0/0 | 0 | HIGH |
| S4 | 150/150/150/150/75/75 | 750 | LOW |
| S5 | 75/75/100/100/74/75 | 499 | HIGH |

精确输入与公式以 `tests/test_rules_and_scoring.py` 和冻结架构文档为准。

## 阶段 A 篡改测试

`tests/test_decision_and_evidence.py` 覆盖：

- 同时伪造六项贡献、总分、等级和证据引用；
- 在可信快照应命中 R002 时同步伪造 `matched=false` 与相关证据；
- 上游伪造 VALID、复制 CONSISTENT 报告或修改已签发结果；
- customer/data/rule/model 版本冲突、证据重复或缺失。

Validator 使用可信快照和现有冻结实现重算；不复制第二套公式。失败路径不得输出确定性 PASS/REJECT。

## 阶段 B 篡改测试

`tests/test_explanation.py` 覆盖篡改 score、risk level、规则、`P_SCORE_001`、证据 ID，以及把 Model Risk Factor 提升为拒绝原因。候选解释验证失败后 `explanation=null`，已通过阶段 A 的确定性决策可保留，整体状态为 PARTIAL。

## API 与 Web 自动化

API 测试使用 FastAPI TestClient 覆盖 PASS、规则拒绝、评分门槛拒绝、非法输入、不存在客户、禁用 LLM、离线行为和响应契约。

Web 测试验证页面/静态资源可加载、PASS/REJECT/PARTIAL 映射、阶段 B 门禁、三类内容分区、版本与免责声明、复制/下载入口、`textContent` 安全渲染和无外部资产。它们是 Python/静态资源级自动化，不是 Playwright、Selenium 或真实浏览器端到端测试。

## 本轮实测结果

CP-05A 于 2026-11-01 在 Windows/PowerShell、本地 Python 3.11 环境实际执行：

- `uv run pytest -q`：137 passed；另有 1 条 Starlette TestClient/httpx2 弃用警告
- `uv run ruff check .`：All checks passed
- `git diff --check`：通过（Git 仅提示工作区 LF 将来可能转换为 CRLF，不是 diff 错误）

## 尚未完成的验证与已知限制

- 未执行真实浏览器人工验收；桌面/手机布局、剪贴板权限和文件下载需人工确认。
- 没有浏览器自动化框架，不宣称跨浏览器兼容性。
- 本地工具 2 秒与 Mock LLM 5 秒是架构设计目标，不是已验证 SLA。
- 当前没有 GitHub Actions 工作流；验证依赖维护者本地运行命令。
- TestClient 可能产生 Starlette 关于 httpx2 的上游弃用警告。
- 没有真实 LLM、外部网络、数据库、生产认证或真实金融效果验证。

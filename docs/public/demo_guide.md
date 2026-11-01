# CreditPilot V0.1 本地演示手册

## 环境要求

- Windows 11 与 PowerShell
- Python 3.11
- [uv](https://docs.astral.sh/uv/)（只用于安装和运行本地项目依赖）

## 准备与启动

在项目根目录执行：

```powershell
uv sync
uv run uvicorn creditpilot.main:app --reload
```

浏览器打开 `http://127.0.0.1:8000/`。服务只需本机访问；演示不要求 API Key，也不会调用外部服务。

## 可重复演示

### 1. PASS：DEMO-0001

保留默认问题，提交 `DEMO-0001`。当前数据和版本下预期：

- `analysis_status=SUCCESS`
- `decision_status=PASS`
- score 935，risk level LOW
- 规则命中 0/4
- 页面显示“未触发模拟拒绝规则”及评分门槛已满足

这里的 PASS 仅表示未触发模拟拒绝条件，不是银行授信批准。

### 2. 规则拒绝：DEMO-0002

提交 `DEMO-0002`。当前数据和版本下预期：

- `analysis_status=SUCCESS`
- `decision_status=REJECT`
- score 869，risk level LOW
- 命中 R001，原因 `P_R001_IDENTITY_UNVERIFIED`

该场景刻意展示：模型等级 LOW 与策略规则拒绝可以并存，Model Risk Factor 不自动等于 Policy Decision Reason。

### 3. 非法客户编号

输入 `INVALID-ID`。前端/接口应显示 `INVALID_INPUT`、`NOT_EVALUATED`，不生成评分、规则或模拟决策。API 对应 HTTP 422。

### 4. 不存在客户

输入格式合法但不存在的 `DEMO-9999`。应显示 `NOT_FOUND`、`NOT_EVALUATED`，API 对应 HTTP 404。

### 5. 查看报告与证据

成功分析后依次检查：

1. score、risk level 与评分门槛；
2. 命中规则与全部四条执行记录；
3. Policy Decision Reason 与六项 Model Risk Factor 的独立区域；
4. 经阶段 B 验证的解释与 Business Guidance；
5. data/rule/model/strategy 版本、阶段 A/B 摘要和 evidence ID；
6. “查看原始结构化 JSON”。

使用“复制 JSON”或“下载 JSON”保存当前 API 响应。下载内容是演示报告，不应作为真实授信材料。

## 仅由测试夹具演示的场景

### 评分门槛拒绝

默认 30 条数据没有承诺一个“无规则命中且 score < 500”的固定客户，因此不要虚构演示编号。使用已有离线测试：

```powershell
uv run pytest -q tests/test_analyze_api.py::test_analyze_score_policy_reject
uv run pytest -q tests/test_explanation.py::test_score_only_rejection_uses_p_score_001
```

### 阶段 B 失败

生产路径不会提供篡改开关。使用现有测试注入验证候选解释被隐藏、已验证决策被保留且分析状态降为 PARTIAL：

```powershell
uv run pytest -q tests/test_explanation.py::test_orchestrator_hides_failed_candidate_but_keeps_decision
```

## 常见问题

### `uv` 或 Python 版本不匹配

运行 `python --version` 与 `uv python list`，确认使用 Python 3.11；然后重新执行 `uv sync`。

### 端口 8000 被占用

```powershell
uv run uvicorn creditpilot.main:app --reload --port 8001
```

随后访问 `http://127.0.0.1:8001/`。

### 页面能打开但分析失败

先访问 `/health`；再检查浏览器请求是否发送到同一 FastAPI 服务。`mode` 必须为 `rules`，当前 `llm` 未启用。

### 测试出现 Starlette/httpx2 提示

当前测试可能显示 TestClient 的上游弃用警告；它不等于测试失败。不要为消除警告擅自升级冻结依赖，后续应单独评估兼容性。

## 人工验收状态与免责声明

自动化测试验证了路由、静态资源、DOM 安全约束和数据映射逻辑，但本轮没有执行真实浏览器人工验收；响应式布局、复制权限提示和下载交互仍需人工检查。

所有客户、规则、评分和结果均为原创合成演示内容。系统不提供真实授信决策或建议，不得用于真实金融业务。


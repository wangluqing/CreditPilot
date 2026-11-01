# CreditPilot V0.1

CreditPilot 是面向 AI 信贷风险解释与决策辅助场景的 Copilot。本项目 V0.1 仅用于公开工程演示与技术验证，不是生产信贷系统。

## 数据与安全声明

项目中的客户画像、规则、评分、决策和文档案例均为 100% 原创合成模拟数据。项目不接入真实信贷系统，不包含真实客户数据、征信数据或前雇主保密资料，也不执行真实审批或额度调整。

## 技术栈

- Python 3.11
- uv
- FastAPI、Pydantic、Uvicorn
- pytest、HTTPX、Ruff

## 本地运行

```powershell
uv sync
uv run uvicorn creditpilot.main:app --reload
```

服务启动后可访问 `http://127.0.0.1:8000/health`。

## 测试与检查

```powershell
uv run pytest -q
uv run ruff check .
```

## 当前已实现

- 基于 src layout 的 Python 工程骨架
- 最小 FastAPI 应用
- `GET /health` 健康检查
- 离线自动化测试与 Ruff 静态检查基线

## 后续阶段

CP-01 至 CP-07 将按任务范围逐步加入合成领域数据、确定性规则与评分、工具编排、可追溯解释、评估和演示界面。当前尚未实现 Agent、风控模型、规则引擎、数据库或 Web 界面。

## 免责声明

本项目不具备真实信用风险预测或审批能力，输出不得用于真实金融决策。任何真实业务决策必须由具备授权的人员依据适用法规和机构制度作出。

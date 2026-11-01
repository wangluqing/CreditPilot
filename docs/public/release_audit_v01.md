# CreditPilot V0.1 公开发布审计报告

## 1. 审计标识

| 项目 | 值 |
|---|---|
| 审计任务 | CP-05B |
| 审计日期 | 2026-11-01（Asia/Shanghai） |
| 审计基线 HEAD | `ac7abc52899a1a3a976226652212c320956fe4f9` |
| 分支 | `main` |
| 审计方式 | 本地、离线优先；未上传仓库到第三方扫描服务 |

状态定义：**PASS** 已验证通过；**PENDING** 尚未验证；**FAIL** 已确认失败；**NOT_APPLICABLE** 不适用。

## 2. 审计范围

本轮检查当前跟踪文件及可达 Git 历史、合成数据、Python/JavaScript 网络调用、DOM 渲染、CSP、调试暴露、`pyproject.toml`、`uv.lock`、安装环境许可证元数据、Apache-2.0 LICENSE、测试、Ruff、冻结安装以及新增 GitHub Actions 配置。

本轮未修改产品业务逻辑、冻结需求、规则、评分公式、依赖版本或测试，也未执行联网 CVE 查询、远端 CI、真实浏览器验收、发布、推送或打标签。

## 3. 审计结论总表

| 项目 | 状态 | 结论 |
|---|---|---|
| 当前跟踪文件凭证扫描 | PASS | 未发现已填充 API Key、Token、密码、私钥模式 |
| 可达 Git 历史凭证扫描 | PASS | 未发现已填充凭证模式；输出仅保留脱敏位置策略 |
| 合成数据与业务边界 | PASS | 30 条 `synthetic-v1` 原创演示记录，无姓名、证件、电话、银行账号或真实机构字段 |
| 被跟踪的缓存/环境/日志/数据库 | PASS | 未发现；`.env.example` 是空值模板，不是实际 `.env` |
| 外部网络与隐藏遥测 | PASS | 应用代码仅有同源 `fetch("/analyze")`；无 exporter、外部 URL 或跟踪脚本 |
| DOM 渲染与 CSP | PASS | 未使用 `innerHTML` 等危险 API；CSP 与同源静态资源及 API 请求一致 |
| 调试接口 | PASS | 未启用 FastAPI debug；Web 路由不进入 OpenAPI；未发现堆栈或路径回显 |
| 锁文件一致性 | PASS | `uv sync --frozen` 成功；Python 锁定为 3.11 系列 |
| 自动化测试 | PASS | 本轮 `uv run pytest -q` 实测结果见第 4 节 |
| Ruff | PASS | 本轮 `uv run ruff check .` 实测结果见第 4 节 |
| Apache-2.0 项目许可证 | PASS | 标准 2.0 条款完整，包含 `Copyright 2026 Jack Wang` |
| 第三方许可证元数据 | PASS | 锁定包元数据为 MIT/BSD/Apache/PSF/MPL 等；详见第 5 节 |
| 最新 CVE 全量审计 | PENDING | 本轮离线且未使用联网漏洞数据库，不能宣称完成 |
| GitHub Actions 远端运行 | PENDING | 已配置但尚无远端运行证据 |
| 浏览器人工验收 | PENDING | 未执行真实桌面/手机浏览器人工验收 |
| 公开作者邮箱确认 | PASS | 项目负责人已批准从当前公开元数据移除邮箱；历史披露风险已知并接受 |

## 4. 质量与回归结果

执行命令：

```powershell
uv sync --frozen
uv run pytest -q
uv run ruff check .
git diff --check
```

CP-05B 本轮实测结果：

- `uv sync --frozen`：PASS，`Checked 25 packages`
- `uv run pytest -q`：PASS，137 passed；另有 1 条已知 Starlette TestClient/httpx2 弃用警告
- `uv run ruff check .`：PASS，`All checks passed!`
- `git diff --check`：PASS，无空白错误

回归范围包括规则/评分边界、S1–S5、阶段 A 协同篡改、阶段 B 解释阻断、API 状态契约、Web 展示门禁和默认客户结果。默认客户已在审计前核对：`DEMO-0001` 为 PASS/935/LOW，`DEMO-0002` 为 R001 REJECT/869/LOW。

## 5. 依赖与许可证

### 5.1 顶层依赖

| 分组 | 依赖 | 用途判断 |
|---|---|---|
| runtime | FastAPI、Pydantic、Uvicorn | API、严格数据模型和本地服务所需 |
| dev | HTTPX、pytest、Ruff | TestClient、自动化测试和静态检查所需 |

未发现 LangGraph、MCP、RAG、数据库驱动、前端框架或真实 LLM SDK。未擅自升级依赖。

### 5.2 锁定包许可证元数据

离线读取当前锁定并安装的包元数据：

- MIT：FastAPI、Pydantic、pydantic-core、pytest、Ruff、h11、anyio、annotated-doc、annotated-types、iniconfig、pluggy、typing-inspection；
- BSD-3-Clause/BSD：Uvicorn、Starlette、HTTPX、httpcore、Click、idna、colorama；
- Apache-2.0：opentelemetry-api；
- Apache-2.0 OR BSD-2-Clause：packaging；
- BSD-2-Clause：Pygments；
- PSF-2.0：typing-extensions；
- MPL-2.0：certifi。

这些结论来自本地包的 `License-Expression`、License 或分类器元数据，不替代发布方对每个上游 LICENSE 文件的法律审查。`uv-build` 是 PEP 517 构建后端，未出现在同步后的运行/开发环境中，因此其本地元数据许可证未单独确认；发布源码前不构成运行时打包内容，但如分发构建产物应进一步核查。

`opentelemetry-api` 是锁定 FastAPI 版本的传递依赖；项目代码未配置 exporter、采集器或外部遥测发送。

### 5.3 漏洞审计局限

本轮没有联网查询 OSV、GitHub Advisory Database 或 PyPI 最新公告，因此只验证了锁定、安装与许可证元数据，不能称为最新或完整 CVE 审计。建议发布负责人在允许联网且不上传源码的环境中，对锁文件包名和版本执行独立漏洞数据库查询。

## 6. 安全与隐私发现

### LOW-01：历史作者邮箱披露风险

- 状态：PASS（当前文件已修复；历史风险已由项目负责人接受）
- 位置：历史 `pyproject.toml` 作者元数据
- 说明：旧作者邮箱曾被 Git 跟踪。当前作者元数据仅保留 `Jack Wang`，公开文档不再记录完整邮箱；根据项目负责人决定，不重写 Git 历史。
- 建议：公开交付时明确披露历史中可能恢复旧邮箱，不把当前文件扫描通过表述为历史已清除。

### INFO-01：`.env.example`

- 状态：PASS
- 说明：历史敏感文件名扫描会命中 `.env.example`，但文件仅含预留变量与空 `DEEPSEEK_API_KEY`，未发现真实值；实际 `.env` 已由 `.gitignore` 排除。

### INFO-02：TestClient 弃用警告

- 状态：PENDING
- 说明：测试通过，但 Starlette TestClient 输出关于 httpx2 的弃用警告。当前不擅自升级冻结依赖；后续应单独评估依赖兼容性。

未发现 HIGH、CRITICAL 或已确认 FAIL 的安全问题。

## 7. Web 与 API 审计

- 原生前端使用 `textContent`/DOM 节点创建，不使用 `innerHTML`、`outerHTML`、`eval` 或动态 Function。
- 唯一 fetch 目标是同源 `/analyze`；无 CDN、外部字体、分析脚本或隐藏遥测。
- 页面 CSP 为 `default-src 'self'`，脚本、样式、连接和图片均限同源，禁用 object、base 和 framing；与当前资源加载一致。
- FastAPI 未设置 `debug=True`；应用错误返回稳定通用信息，不回显堆栈、密钥或内部路径。
- `/docs` 和 `/openapi.json` 是 FastAPI 默认开发文档，当前不含秘密，但若未来对公网部署，应由部署层决定是否关闭或访问控制。
- 产品页面、README 与响应免责声明均明确为合成数据、模拟策略、非真实授信。

## 8. GitHub Actions CI

新增 `.github/workflows/ci.yml`：

- Ubuntu `ubuntu-latest`；
- Python 3.11、uv 0.12.9；
- `uv sync --frozen`；
- `uv run pytest -q`；
- `uv run ruff check .`；
- 顶层最小权限 `contents: read`；
- 10 分钟超时；
- 不需要 secrets，不部署、不发布、不推送。

使用 GitHub 官方 `actions/checkout@v4` 与 Astral 官方 `astral-sh/setup-uv@v7`。本地只验证 YAML 文本结构、字段和对应命令；没有远端 GitHub Actions 运行证据，状态为 PENDING。

## 9. 浏览器人工验收

状态：**PENDING**。本轮未执行真实浏览器桌面/手机验收，不能把 TestClient 和静态资源测试宣传为浏览器端到端验证。仍需人工确认响应式布局、复制权限、JSON 下载及常见浏览器行为。

## 10. 发布门禁建议

当前建议：**NO-GO（暂缓公开发布）**。

原因不是已发现高风险缺陷，而是正式公开前仍有以下 PENDING 门禁：

1. 首次远端 GitHub Actions 运行尚未取得通过证据；
2. 浏览器人工验收尚未完成；
3. 若发布流程要求最新漏洞态势，需要在不上传源码的前提下补充联网依赖漏洞查询。

上述项目完成并留存证据后，可由项目负责人重新作出 GO/NO-GO 决定。本报告不构成自动发布授权。

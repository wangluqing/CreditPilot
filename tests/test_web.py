"""Route, asset, mapping, and static security checks for the local Web UI."""

from pathlib import Path

from fastapi.testclient import TestClient

from creditpilot.main import app

client = TestClient(app)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"


def test_web_root_is_available_with_local_security_headers() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "CreditPilot V0.1" in response.text
    assert "100% 合成数据" in response.text
    assert "非银行审批系统" in response.text
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_same_origin_static_assets_are_loadable() -> None:
    css = client.get("/static/styles.css")
    javascript = client.get("/static/app.js")

    assert css.status_code == 200
    assert javascript.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert "javascript" in javascript.headers["content-type"]
    assert "@media (max-width: 560px)" in css.text


def test_frontend_maps_pass_reject_score_and_partial_states() -> None:
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for contract_field in (
        "analysis_status",
        "decision_status",
        "score_policy.pass_threshold_met",
        "rule_summary.matched",
        "rule_summary.total",
        "policy_reasons",
        "model_risk_factors",
    ):
        assert contract_field in source
    assert 'data.analysis_status === "PARTIAL"' in source
    assert "确定性模拟决策已保留" in source
    assert "未经验证的候选解释不会展示" in source


def test_verified_explanation_requires_consistent_stage_b() -> None:
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'report.stage === "B"' in source
    assert 'report.status === "CONSISTENT"' in source
    assert "stageBIsValid(data) && data.explanation" in source
    assert "section.hidden = !verified" in source


def test_policy_reasons_and_model_factors_have_separate_regions() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="policy-reasons"' in html
    assert 'id="model-factors"' in html
    assert "renderPolicyReasons(data)" in source
    assert "renderModelFactors(data)" in source
    assert "模型贡献，不自动等同于拒绝原因" in source


def test_versions_evidence_validation_and_disclaimer_are_present() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for element_id in (
        "versions",
        "validation-reports",
        "evidence-list",
        "raw-json",
        "disclaimer",
    ):
        assert f'id="{element_id}"' in html
    assert "evidence_id" in source
    assert "data.versions?.data_version" in source
    assert "data.versions?.rule_version" in source
    assert "data.versions?.model_version" in source


def test_copy_and_download_report_controls_are_implemented() -> None:
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "navigator.clipboard.writeText" in source
    assert "new Blob" in source
    assert "URL.createObjectURL" in source
    assert "anchor.download" in source


def test_frontend_uses_safe_text_rendering_and_no_external_assets() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    source = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "textContent" in source
    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "eval(" not in source
    assert "http://" not in html
    assert "https://" not in html
    assert "cdn" not in html.lower()


def test_web_does_not_change_health_or_analyze_contract() -> None:
    health = client.get("/health")
    analysis = client.post(
        "/analyze",
        json={
            "customer_id": "DEMO-0001",
            "question": "解释模拟结果",
            "mode": "rules",
        },
    )

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert analysis.status_code == 200
    assert analysis.json()["decision_status"] == "PASS"
    assert "未触发模拟拒绝规则" in analysis.json()["explanation"]["summary"]


def test_invalid_and_not_found_responses_have_safe_ui_messages() -> None:
    invalid = client.post(
        "/analyze",
        json={"customer_id": "bad-id", "question": "解释", "mode": "rules"},
    )
    missing = client.post(
        "/analyze",
        json={"customer_id": "DEMO-9999", "question": "解释", "mode": "rules"},
    )

    assert invalid.status_code == 422
    assert invalid.json()["analysis_status"] == "INVALID_INPUT"
    assert missing.status_code == 404
    assert missing.json()["analysis_status"] == "NOT_FOUND"
    assert invalid.json()["score"] is None
    assert missing.json()["rule_results"] == []

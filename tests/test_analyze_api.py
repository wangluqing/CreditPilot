"""HTTP contract tests for POST /analyze."""

import importlib
import socket

import pytest
from fastapi.testclient import TestClient

from creditpilot.agent.orchestrator import AnalysisOrchestrator
from creditpilot.main import app
from creditpilot.models.customer import DATA_VERSION, CustomerRecord
from creditpilot.tools.customer import CustomerTool

client = TestClient(app)
api_module = importlib.import_module("creditpilot.api.analyze")


def payload(customer_id: str, **overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "customer_id": customer_id,
        "question": "Explain this synthetic customer's risk result",
        "mode": "rules",
    }
    result.update(overrides)
    return result


def test_analyze_pass_response_contract() -> None:
    response = client.post("/analyze", json=payload("DEMO-0001"))
    body = response.json()

    assert response.status_code == 200
    assert (body["analysis_status"], body["decision_status"]) == (
        "SUCCESS",
        "PASS",
    )
    assert body["rule_summary"]["total"] == 4
    assert body["rule_summary"]["matched"] == 0
    assert body["score_policy"]["pass_threshold_met"] is True
    assert body["score_policy"]["condition_triggered"] is False
    assert body["policy_reasons"] == []
    assert "real credit approval" in body["disclaimer"]


def test_analyze_rule_reject_is_http_200() -> None:
    response = client.post("/analyze", json=payload("DEMO-0002"))
    body = response.json()

    assert response.status_code == 200
    assert body["decision_status"] == "REJECT"
    assert any(reason["source_id"] == "R001" for reason in body["policy_reasons"])


def score_499_orchestrator() -> AnalysisOrchestrator:
    snapshot = CustomerRecord.model_validate(
        {
            "customer_id": "DEMO-9799",
            "data_version": DATA_VERSION,
            "verified_identity": True,
            "monthly_income": 5_000,
            "monthly_debt_payment": 2_500,
            "employment_months": 60,
            "credit_history_months": 120,
            "delinquency_count_12m": 2,
            "inquiry_count_6m": 4,
            "requested_amount": 42_400,
            "synthetic_region": "SYN-WEST",
            "scenario_label": "api-score-499",
        }
    )
    return AnalysisOrchestrator(
        CustomerTool([snapshot.model_dump(mode="python")])
    )


def test_analyze_score_policy_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_module, "orchestrator", score_499_orchestrator())

    response = client.post("/analyze", json=payload("DEMO-9799"))
    body = response.json()

    assert response.status_code == 200
    assert body["score"] == 499
    assert body["rule_summary"]["matched"] == 0
    assert body["policy_reasons"][0]["reason_id"] == "P_SCORE_001"
    assert body["policy_reasons"][0]["source_type"] == "SCORE_POLICY"


@pytest.mark.parametrize(
    "bad_payload,error_code",
    [
        (payload("bad-id"), "INVALID_CUSTOMER_ID"),
        (payload("DEMO-0001", question="   "), "INVALID_QUESTION"),
        (payload("DEMO-0001", question="bad\u0001question"), "INVALID_QUESTION"),
        (payload("DEMO-0001", mode="other"), "INVALID_MODE"),
        ({"customer_id": "DEMO-0001", "mode": "rules"}, "INVALID_QUESTION"),
    ],
)
def test_invalid_analyze_requests_return_safe_422(
    bad_payload: dict[str, object], error_code: str
) -> None:
    response = client.post("/analyze", json=bad_payload)
    body = response.json()

    assert response.status_code == 422
    assert (body["analysis_status"], body["decision_status"]) == (
        "INVALID_INPUT",
        "NOT_EVALUATED",
    )
    assert body["error_code"] == error_code
    assert "traceback" not in response.text.lower()
    assert "D:\\" not in response.text


def test_customer_not_found_returns_404_without_decision() -> None:
    response = client.post("/analyze", json=payload("DEMO-9999"))
    body = response.json()

    assert response.status_code == 404
    assert (body["analysis_status"], body["decision_status"]) == (
        "NOT_FOUND",
        "NOT_EVALUATED",
    )
    assert body["error_code"] == "CUSTOMER_NOT_FOUND"


def test_llm_mode_is_explicitly_unavailable() -> None:
    response = client.post(
        "/analyze", json=payload("DEMO-0001", mode="llm")
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "LLM_UNAVAILABLE"
    assert response.json()["decision_status"] == "NOT_EVALUATED"


def test_api_cannot_accept_caller_supplied_validation_or_decision() -> None:
    malicious = payload("DEMO-0001")
    malicious["validation_report"] = {"status": "CONSISTENT"}
    malicious["decision_status"] = "PASS"

    response = client.post("/analyze", json=malicious)

    assert response.status_code == 422
    assert response.json()["analysis_status"] == "INVALID_INPUT"


def test_analyze_does_not_open_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", blocked)
    response = client.post("/analyze", json=payload("DEMO-0001"))

    assert response.status_code == 200

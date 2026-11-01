"""Integration tests for the fixed-order offline orchestrator."""

from creditpilot.agent.orchestrator import AnalysisOrchestrator
from creditpilot.models.analysis import AnalyzeRequest
from creditpilot.models.customer import DATA_VERSION, CustomerRecord
from creditpilot.models.decision import AnalysisStatus, DecisionStatus
from creditpilot.models.risk import RiskModelResult
from creditpilot.tools.customer import CustomerTool
from creditpilot.tools.decision import DecisionTool
from creditpilot.tools.risk_model import RiskModelTool
from creditpilot.tools.rules import RuleEngineTool


def fixture_customer(customer_id: str = "DEMO-9801", **overrides: object):
    data: dict[str, object] = {
        "customer_id": customer_id,
        "data_version": DATA_VERSION,
        "verified_identity": True,
        "monthly_income": 10_000,
        "monthly_debt_payment": 2_000,
        "employment_months": 120,
        "credit_history_months": 240,
        "delinquency_count_12m": 0,
        "inquiry_count_6m": 0,
        "requested_amount": 12_000,
        "synthetic_region": "SYN-NORTH",
        "scenario_label": "orchestrator-test",
    }
    data.update(overrides)
    return CustomerRecord.model_validate(data)


def request(customer_id: str, mode: str = "rules") -> AnalyzeRequest:
    return AnalyzeRequest(
        customer_id=customer_id,
        question="Explain the synthetic result",
        mode=mode,
    )


def orchestrator_for(*customers: CustomerRecord, **kwargs: object):
    tool = CustomerTool([item.model_dump(mode="python") for item in customers])
    return AnalysisOrchestrator(tool, **kwargs)


def test_orchestrator_runs_complete_deterministic_chain() -> None:
    snapshot = fixture_customer()
    result = orchestrator_for(snapshot).analyze(request(snapshot.customer_id))

    assert (result.analysis_status, result.decision_status) == (
        AnalysisStatus.SUCCESS,
        DecisionStatus.PASS,
    )
    assert result.rule_summary is not None
    assert result.rule_summary.total == 4
    assert result.risk_score is not None
    assert len(result.risk_score.factors) == 6
    assert result.validation_reports[0].status == "CONSISTENT"


class TamperingModelTool(RiskModelTool):
    def score(self, *args: object, **kwargs: object) -> RiskModelResult:
        result = super().score(*args, **kwargs)
        return result.model_copy(update={"score": result.score - 1})


class CountingDecisionTool(DecisionTool):
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, *args: object, **kwargs: object):
        self.calls += 1
        return super().decide(*args, **kwargs)


def test_stage_a_failure_is_fail_closed() -> None:
    snapshot = fixture_customer()
    decision = CountingDecisionTool()
    result = orchestrator_for(
        snapshot,
        model_tool=TamperingModelTool(),
        decision_tool=decision,
    ).analyze(request(snapshot.customer_id))

    assert decision.calls == 0
    assert (result.analysis_status, result.decision_status) == (
        AnalysisStatus.PARTIAL,
        DecisionStatus.NEEDS_REVIEW,
    )
    assert result.error_code == "DEPENDENCY_NOT_VALIDATED"


def test_separate_requests_never_mix_customer_evidence() -> None:
    first = fixture_customer("DEMO-9801")
    second = fixture_customer("DEMO-9802", verified_identity=False)
    service = orchestrator_for(first, second)

    first_result = service.analyze(request(first.customer_id))
    second_result = service.analyze(request(second.customer_id))

    assert first_result.customer_id == first.customer_id
    assert second_result.customer_id == second.customer_id
    first_ids = {item.evidence_id for item in first_result.evidence_references}
    second_ids = {item.evidence_id for item in second_result.evidence_references}
    assert first_ids.isdisjoint(second_ids)


def test_same_input_response_is_reproducible_except_request_id() -> None:
    snapshot = fixture_customer()
    service = orchestrator_for(snapshot)

    first = service.analyze(request(snapshot.customer_id)).model_dump(mode="json")
    second = service.analyze(request(snapshot.customer_id)).model_dump(mode="json")
    first.pop("request_id")
    second.pop("request_id")

    assert first == second


def test_llm_mode_is_disabled_without_running_customer_tool() -> None:
    snapshot = fixture_customer()
    result = orchestrator_for(snapshot).analyze(request(snapshot.customer_id, "llm"))

    assert (result.analysis_status, result.decision_status) == (
        AnalysisStatus.FAILED,
        DecisionStatus.NOT_EVALUATED,
    )
    assert result.error_code == "LLM_UNAVAILABLE"
    assert result.evidence_references == ()


class ExplodingRuleTool(RuleEngineTool):
    def evaluate(self, *args: object, **kwargs: object):
        raise RuntimeError("internal path and payload must not escape")


def test_required_tool_exception_is_not_mapped_to_reject() -> None:
    snapshot = fixture_customer()
    result = orchestrator_for(snapshot, rule_tool=ExplodingRuleTool()).analyze(
        request(snapshot.customer_id)
    )

    assert (result.analysis_status, result.decision_status) == (
        AnalysisStatus.FAILED,
        DecisionStatus.NOT_EVALUATED,
    )
    assert result.error_code == "TOOL_UNAVAILABLE"
    assert "internal path" not in result.errors[0].message

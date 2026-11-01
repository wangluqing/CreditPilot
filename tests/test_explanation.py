"""Deterministic template rendering and stage-B validation tests."""

import pytest

from creditpilot.agent.orchestrator import AnalysisOrchestrator
from creditpilot.models.analysis import AnalyzeRequest
from creditpilot.models.customer import DATA_VERSION, CustomerRecord
from creditpilot.models.decision import AnalysisStatus, DecisionStatus
from creditpilot.models.explanation import PolicyReasonExplanation
from creditpilot.models.risk import RiskLevel
from creditpilot.tools.customer import CustomerTool
from creditpilot.tools.decision import DecisionTool
from creditpilot.tools.evidence import EvidenceValidator
from creditpilot.tools.explanation import FixedTemplateEngine
from creditpilot.tools.risk_model import RiskModelTool
from creditpilot.tools.rules import RuleEngineTool


def customer(**overrides: object) -> CustomerRecord:
    data: dict[str, object] = {
        "customer_id": "DEMO-9701",
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
        "scenario_label": "explanation-test",
    }
    data.update(overrides)
    return CustomerRecord.model_validate(data)


def score_499_customer(**overrides: object) -> CustomerRecord:
    return customer(
        monthly_income=5_000,
        monthly_debt_payment=2_500,
        employment_months=60,
        credit_history_months=120,
        delinquency_count_12m=2,
        inquiry_count_6m=4,
        requested_amount=42_400,
        **overrides,
    )


def build(snapshot: CustomerRecord):
    lookup = CustomerTool([snapshot.model_dump(mode="python")]).lookup(
        snapshot.customer_id
    )
    rules = RuleEngineTool().evaluate(snapshot)
    model = RiskModelTool().score(snapshot)
    validator = EvidenceValidator()
    stage_a = validator.validate_stage_a(snapshot, lookup.evidence, rules, model)
    decision = DecisionTool().decide(stage_a, rules, model)
    candidate = FixedTemplateEngine().render(decision, rules, model)
    return validator, stage_a, decision, rules, model, candidate


def validate_candidate(snapshot: CustomerRecord, mutate=None):
    validator, stage_a, decision, rules, model, candidate = build(snapshot)
    if mutate is not None:
        candidate = mutate(candidate)
    report = validator.validate_stage_b(
        candidate, stage_a, decision, rules, model
    )
    return candidate, report


def test_pass_explanation_preserves_frozen_wording_and_score_gate() -> None:
    candidate, report = validate_candidate(customer())

    assert report.status == "CONSISTENT"
    assert "未触发模拟拒绝规则" in candidate.summary
    assert candidate.score_threshold_met is True
    assert candidate.business_guidance.template_id == "BG_NO_REJECT_RULE"
    assert "不表示真实授信批准" in candidate.business_guidance.text


@pytest.mark.parametrize(
    "overrides,rule_id",
    [
        ({"verified_identity": False}, "R001"),
        ({"delinquency_count_12m": 3}, "R002"),
        ({"monthly_debt_payment": 8_000}, "R003"),
        ({"requested_amount": 120_001}, "R004"),
    ],
)
def test_each_single_rule_has_traceable_chinese_explanation(
    overrides: dict[str, object], rule_id: str
) -> None:
    candidate, report = validate_candidate(customer(**overrides))

    assert report.status == "CONSISTENT"
    assert candidate.matched_rule_ids == (rule_id,)
    item = candidate.policy_decision_reasons[0]
    assert item.source_id == rule_id
    assert item.actual_value is not None
    assert item.evidence_ids


def test_multiple_rules_and_score_gate_remain_separate() -> None:
    snapshot = score_499_customer(verified_identity=False)
    candidate, report = validate_candidate(snapshot)

    assert report.status == "CONSISTENT"
    assert candidate.matched_rule_ids == ("R001",)
    assert {item.source_type for item in candidate.policy_decision_reasons} == {
        "RULE",
        "SCORE_POLICY",
    }
    assert candidate.score_threshold_met is False


def test_multiple_rule_rejection_lists_every_matched_rule() -> None:
    candidate, report = validate_candidate(
        customer(
            verified_identity=False,
            delinquency_count_12m=3,
            monthly_debt_payment=8_000,
        )
    )

    assert report.status == "CONSISTENT"
    assert candidate.matched_rule_ids == ("R001", "R002", "R003")
    assert {item.source_id for item in candidate.policy_decision_reasons} == {
        "R001",
        "R002",
        "R003",
    }


def test_score_only_rejection_uses_p_score_001() -> None:
    candidate, report = validate_candidate(score_499_customer())

    assert report.status == "CONSISTENT"
    assert candidate.matched_rule_ids == ()
    assert [item.reason_id for item in candidate.policy_decision_reasons] == [
        "P_SCORE_001"
    ]
    assert "未命中模拟拒绝规则" in candidate.summary


def test_six_factors_sum_to_explained_score() -> None:
    candidate, _ = validate_candidate(customer())

    assert len(candidate.model_risk_factors) == 6
    assert (
        sum(item.contribution for item in candidate.model_risk_factors)
        == candidate.score
    )
    assert all(
        "不自动等同于拒绝原因" in item.text
        for item in candidate.model_risk_factors
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item.model_copy(update={"score": item.score - 1}),
        lambda item: item.model_copy(update={"risk_level": RiskLevel.HIGH}),
        lambda item: item.model_copy(update={"matched_rule_ids": ("R999",)}),
        lambda item: item.model_copy(update={"score_threshold_met": False}),
        lambda item: item.model_copy(update={"evidence_ids": ("EV-NOT-FOUND",)}),
        lambda item: item.model_copy(
            update={"summary": item.summary.replace(str(item.score), "999")}
        ),
    ],
)
def test_stage_b_blocks_tampered_fact_slots(mutation) -> None:
    _, report = validate_candidate(customer(), mutation)

    assert report.status == "INCONSISTENT"
    assert report.blocked_output == "CANDIDATE_EXPLANATION"


def test_stage_b_blocks_forged_score_policy_reason() -> None:
    def forge(candidate):
        fake = PolicyReasonExplanation(
            reason_id="P_SCORE_001",
            source_type="SCORE_POLICY",
            source_id="P_SCORE_001",
            condition="score < 500",
            actual_value=935,
            text="伪造的评分门槛事实。",
            evidence_ids=(candidate.evidence_ids[0],),
        )
        return candidate.model_copy(
            update={"policy_decision_reasons": (fake,)}
        )

    _, report = validate_candidate(customer(), forge)

    assert report.status == "INCONSISTENT"


def test_stage_b_blocks_model_factor_promoted_to_policy_reason() -> None:
    def forge(candidate):
        factor = candidate.model_risk_factors[0]
        fake = PolicyReasonExplanation(
            reason_id=factor.factor_id,
            source_type="RULE",
            source_id=factor.factor_id,
            condition="低贡献",
            actual_value=factor.contribution,
            text="将模型因素错误写成拒绝原因。",
            evidence_ids=factor.evidence_ids,
        )
        return candidate.model_copy(
            update={"policy_decision_reasons": (fake,)}
        )

    _, report = validate_candidate(customer(), forge)

    assert report.status == "INCONSISTENT"


class TamperingTemplateEngine(FixedTemplateEngine):
    def render(self, *args: object, **kwargs: object):
        candidate = super().render(*args, **kwargs)
        return candidate.model_copy(update={"score": candidate.score - 1})


def test_orchestrator_hides_failed_candidate_but_keeps_decision() -> None:
    snapshot = customer()
    service = AnalysisOrchestrator(
        CustomerTool([snapshot.model_dump(mode="python")]),
        template_engine=TamperingTemplateEngine(),
    )
    result = service.analyze(
        AnalyzeRequest(
            customer_id=snapshot.customer_id,
            question="解释模拟结果",
            mode="rules",
        )
    )

    assert (result.analysis_status, result.decision_status) == (
        AnalysisStatus.PARTIAL,
        DecisionStatus.PASS,
    )
    assert result.explanation is None
    assert result.error_code == "EXPLANATION_UNSUPPORTED"
    assert result.validation_reports[1].status == "INCONSISTENT"

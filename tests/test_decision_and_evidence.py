"""Offline stage-A evidence validation and deterministic policy tests."""

import socket

import pytest

from creditpilot.models.customer import DATA_VERSION, CustomerRecord
from creditpilot.models.decision import (
    AnalysisStatus,
    DecisionStatus,
    EvidenceStatus,
    ValidationReportStatus,
)
from creditpilot.models.risk import RiskLevel, ToolErrorCode
from creditpilot.tools.customer import CustomerTool
from creditpilot.tools.decision import DecisionTool
from creditpilot.tools.evidence import EvidenceValidator
from creditpilot.tools.risk_model import RiskModelTool
from creditpilot.tools.rules import RuleEngineTool


def customer(**overrides: object) -> CustomerRecord:
    data: dict[str, object] = {
        "customer_id": "DEMO-9901",
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
        "scenario_label": "decision-test",
    }
    data.update(overrides)
    return CustomerRecord.model_validate(data)


def tool_outputs(snapshot: CustomerRecord):
    lookup = CustomerTool([snapshot.model_dump(mode="python")]).lookup(
        snapshot.customer_id
    )
    return (
        lookup.evidence,
        RuleEngineTool().evaluate(snapshot),
        RiskModelTool().score(snapshot),
    )


def validate(snapshot: CustomerRecord, *, rules=None, model=None, evidence=None):
    customer_evidence, rule_result, model_result = tool_outputs(snapshot)
    report = EvidenceValidator().validate_stage_a(
        snapshot,
        customer_evidence if evidence is None else evidence,
        rule_result if rules is None else rules,
        model_result if model is None else model,
    )
    return (
        report,
        rule_result if rules is None else rules,
        model_result if model is None else model,
    )


def decide(snapshot: CustomerRecord):
    report, rules, model = validate(snapshot)
    return DecisionTool().decide(report, rules, model)


def test_pass_when_no_rule_matches_and_score_is_at_least_500() -> None:
    result = decide(customer())

    assert (result.analysis_status, result.decision_status) == (
        AnalysisStatus.SUCCESS,
        DecisionStatus.PASS,
    )
    assert result.policy_reasons == ()
    assert result.business_guidance.template_ids == ("BG_NO_REJECT_RULE",)


@pytest.mark.parametrize(
    "overrides,expected_source",
    [
        ({"verified_identity": False}, "R001"),
        ({"delinquency_count_12m": 3}, "R002"),
        ({"monthly_debt_payment": 8_000}, "R003"),
        ({"requested_amount": 120_001}, "R004"),
    ],
)
def test_each_rule_match_rejects_with_its_own_reason(
    overrides: dict[str, object], expected_source: str
) -> None:
    result = decide(customer(**overrides))

    assert result.decision_status is DecisionStatus.REJECT
    assert expected_source in {reason.source_id for reason in result.policy_reasons}


def test_multiple_rule_matches_preserve_all_policy_reasons() -> None:
    result = decide(
        customer(
            verified_identity=False,
            delinquency_count_12m=3,
            monthly_debt_payment=8_000,
        )
    )

    assert {reason.source_id for reason in result.policy_reasons} == {
        "R001",
        "R002",
        "R003",
    }


@pytest.mark.parametrize(
    "requested_amount,expected_score,expected_decision",
    [(42_400, 499, DecisionStatus.REJECT), (42_000, 500, DecisionStatus.PASS)],
)
def test_score_policy_boundary(
    requested_amount: int,
    expected_score: int,
    expected_decision: DecisionStatus,
) -> None:
    snapshot = customer(
        monthly_income=5_000,
        monthly_debt_payment=2_500,
        employment_months=60,
        credit_history_months=120,
        delinquency_count_12m=2,
        inquiry_count_6m=4,
        requested_amount=requested_amount,
    )
    result = decide(snapshot)

    assert (
        sum(f.rounded_contribution for f in result.model_risk_factors) == expected_score
    )
    assert result.decision_status is expected_decision
    if expected_score == 499:
        assert [(r.reason_id, r.source_type) for r in result.policy_reasons] == [
            ("P_SCORE_001", "SCORE_POLICY")
        ]
        assert all(
            execution.rule_id != "P_SCORE_001"
            for execution in tool_outputs(snapshot)[1].executions
        )


def test_pending_evidence_is_explicitly_validated_before_decision() -> None:
    snapshot = customer()
    customer_evidence, rules, model = tool_outputs(snapshot)
    assert all(
        str(item.validation_status) == "PENDING"
        for item in (*customer_evidence, *rules.evidence, *model.evidence)
    )

    report = EvidenceValidator().validate_stage_a(
        snapshot, customer_evidence, rules, model
    )

    assert report.status is ValidationReportStatus.CONSISTENT
    assert report.evidence_references
    assert all(
        ref.validation_status is EvidenceStatus.VALID
        for ref in report.evidence_references
    )


def test_missing_rule_execution_blocks_pass_and_reject() -> None:
    snapshot = customer()
    evidence, rules, model = tool_outputs(snapshot)
    damaged = rules.model_copy(update={"executions": rules.executions[:-1]})
    report = EvidenceValidator().validate_stage_a(snapshot, evidence, damaged, model)
    result = DecisionTool().decide(report, damaged, model)

    assert result.decision_status is DecisionStatus.NEEDS_REVIEW
    assert result.analysis_status is AnalysisStatus.PARTIAL
    assert result.error_code is ToolErrorCode.DEPENDENCY_NOT_VALIDATED


def test_missing_score_evidence_blocks_decision() -> None:
    snapshot = customer()
    evidence, rules, model = tool_outputs(snapshot)
    damaged = model.model_copy(update={"evidence": model.evidence[:-2]})
    report = EvidenceValidator().validate_stage_a(snapshot, evidence, rules, damaged)

    assert report.status is ValidationReportStatus.INCONSISTENT
    assert (
        DecisionTool().decide(report, rules, damaged).decision_status
        is DecisionStatus.NEEDS_REVIEW
    )


@pytest.mark.parametrize(
    "target,updates",
    [
        ("rules", {"customer_id": "DEMO-9999"}),
        ("rules", {"data_version": "synthetic-v0"}),
        ("rules", {"rule_version": "demo-rules-v0"}),
        ("model", {"model_version": "demo-score-v0"}),
    ],
)
def test_identity_and_version_conflicts_block_decision(
    target: str, updates: dict[str, object]
) -> None:
    snapshot = customer()
    evidence, rules, model = tool_outputs(snapshot)
    if target == "rules":
        rules = rules.model_copy(update=updates)
    else:
        model = model.model_copy(update=updates)

    report = EvidenceValidator().validate_stage_a(snapshot, evidence, rules, model)

    assert report.status is ValidationReportStatus.INCONSISTENT
    assert report.blocked_conclusions == ("PASS", "REJECT")


def test_contribution_sum_tampering_is_detected() -> None:
    snapshot = customer()
    evidence, rules, model = tool_outputs(snapshot)
    damaged = model.model_copy(update={"score": model.score - 1})

    report = EvidenceValidator().validate_stage_a(snapshot, evidence, rules, damaged)

    assert any(issue.field_path == "/model/score" for issue in report.issues)


def test_risk_level_tampering_is_detected() -> None:
    snapshot = customer()
    evidence, rules, model = tool_outputs(snapshot)
    damaged = model.model_copy(update={"risk_level": RiskLevel.HIGH})

    report = EvidenceValidator().validate_stage_a(snapshot, evidence, rules, damaged)

    assert report.status is ValidationReportStatus.INCONSISTENT


def test_rule_matched_tampering_is_detected() -> None:
    snapshot = customer()
    evidence, rules, model = tool_outputs(snapshot)
    altered = rules.executions[0].model_copy(update={"matched": True})
    damaged = rules.model_copy(update={"executions": (altered, *rules.executions[1:])})

    report = EvidenceValidator().validate_stage_a(snapshot, evidence, damaged, model)

    assert any(issue.field_path == "/rules/executions" for issue in report.issues)


def test_duplicate_evidence_id_is_detected() -> None:
    snapshot = customer()
    evidence, rules, model = tool_outputs(snapshot)
    duplicate = model.evidence[1].model_copy(
        update={"evidence_id": model.evidence[0].evidence_id}
    )
    damaged = model.model_copy(
        update={"evidence": (model.evidence[0], duplicate, *model.evidence[2:])}
    )

    report = EvidenceValidator().validate_stage_a(snapshot, evidence, rules, damaged)

    assert any("globally unique" in issue.detail for issue in report.issues)


def test_valid_report_cannot_be_reused_for_mutated_results() -> None:
    snapshot = customer()
    report, rules, model = validate(snapshot)
    mutated = model.model_copy(update={"score": model.score - 1})

    result = DecisionTool().decide(report, rules, mutated)

    assert (result.analysis_status, result.decision_status) == (
        AnalysisStatus.PARTIAL,
        DecisionStatus.NEEDS_REVIEW,
    )


def test_policy_reasons_and_model_factors_are_separate() -> None:
    result = decide(customer(verified_identity=False))

    assert result.policy_reasons[0].source_type == "RULE"
    assert {factor.factor_id for factor in result.model_risk_factors} == {
        "F_EMPLOYMENT",
        "F_HISTORY",
        "F_DEBT_LOAD",
        "F_DELINQUENCY",
        "F_INQUIRY",
        "F_AFFORDABILITY",
    }


def test_same_input_and_versions_produce_same_report_and_decision() -> None:
    first = decide(customer())
    second = decide(customer())

    assert first == second


def test_not_found_and_invalid_input_remain_non_decision_customer_states() -> None:
    tool = CustomerTool([customer().model_dump(mode="python")])

    assert tool.lookup("DEMO-9999").analysis_status.value == "NOT_FOUND"
    assert tool.lookup("bad-id").analysis_status.value == "INVALID_INPUT"


def test_tools_do_not_use_network_or_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", blocked_network)
    result = decide(customer())

    assert result.analysis_status is AnalysisStatus.SUCCESS


def test_coordinated_score_tampering_is_recomputed_from_trusted_snapshot() -> None:
    trusted = customer(
        monthly_income=5_000,
        monthly_debt_payment=2_500,
        employment_months=60,
        credit_history_months=120,
        delinquency_count_12m=2,
        inquiry_count_6m=4,
        requested_amount=42_400,
    )
    forged_source = customer(
        monthly_income=5_000,
        monthly_debt_payment=2_000,
        employment_months=120,
        credit_history_months=240,
        delinquency_count_12m=1,
        inquiry_count_6m=2,
        requested_amount=36_000,
    )
    customer_evidence, rules, _ = tool_outputs(trusted)
    coordinated_forgery = RiskModelTool().score(forged_source)
    assert coordinated_forgery.score == 750
    assert coordinated_forgery.risk_level is RiskLevel.LOW

    report = EvidenceValidator().validate_stage_a(
        trusted, customer_evidence, rules, coordinated_forgery
    )
    result = DecisionTool().decide(report, rules, coordinated_forgery)

    assert report.status is ValidationReportStatus.INCONSISTENT
    assert result.decision_status is DecisionStatus.NEEDS_REVIEW
    assert result.error_code is ToolErrorCode.DEPENDENCY_NOT_VALIDATED


def test_coordinated_rule_tampering_is_recomputed_from_trusted_snapshot() -> None:
    trusted = customer(delinquency_count_12m=3)
    forged_source = customer(delinquency_count_12m=2)
    customer_evidence, _, model = tool_outputs(trusted)
    coordinated_forgery = RuleEngineTool().evaluate(forged_source)
    r002 = next(
        execution
        for execution in coordinated_forgery.executions
        if execution.rule_id == "R002"
    )
    assert r002.matched is False

    report = EvidenceValidator().validate_stage_a(
        trusted, customer_evidence, coordinated_forgery, model
    )
    result = DecisionTool().decide(report, coordinated_forgery, model)

    assert report.status is ValidationReportStatus.INCONSISTENT
    assert result.decision_status is DecisionStatus.NEEDS_REVIEW


def test_upstream_forged_valid_status_does_not_authorize_decision() -> None:
    snapshot = customer()
    customer_evidence, rules, model = tool_outputs(snapshot)
    forged_item = model.evidence[0].model_copy(
        update={"validation_status": "VALID"}
    )
    forged_model = model.model_copy(
        update={"evidence": (forged_item, *model.evidence[1:])}
    )

    report = EvidenceValidator().validate_stage_a(
        snapshot, customer_evidence, rules, forged_model
    )
    result = DecisionTool().decide(report, rules, forged_model)

    assert report.status is ValidationReportStatus.INCONSISTENT
    assert result.decision_status is DecisionStatus.NEEDS_REVIEW


def test_copied_consistent_report_cannot_bypass_validator_authorization() -> None:
    snapshot = customer()
    issued_report, rules, model = validate(snapshot)
    caller_forged_report = issued_report.model_copy(deep=True)
    assert caller_forged_report == issued_report
    assert caller_forged_report is not issued_report

    result = DecisionTool().decide(caller_forged_report, rules, model)

    assert (result.analysis_status, result.decision_status) == (
        AnalysisStatus.PARTIAL,
        DecisionStatus.NEEDS_REVIEW,
    )
    assert result.error_code is ToolErrorCode.DEPENDENCY_NOT_VALIDATED

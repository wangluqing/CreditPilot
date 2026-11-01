"""Offline deterministic tests for demo-rules-v1 and demo-score-v1."""

import socket
from collections.abc import Mapping

import pytest

from creditpilot.models.customer import DATA_VERSION, CustomerRecord
from creditpilot.models.risk import (
    DEMO_MODEL_VERSION,
    DEMO_RULE_VERSION,
    RiskLevel,
    RuleResult,
    ToolErrorCode,
)
from creditpilot.tools.risk_model import RiskModelTool
from creditpilot.tools.rules import RuleEngineTool


def customer_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "customer_id": "DEMO-9001",
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
        "scenario_label": "isolated-test-fixture",
    }
    data.update(overrides)
    return data


def customer(**overrides: object) -> CustomerRecord:
    return CustomerRecord.model_validate(customer_data(**overrides))


FROZEN_SCORE_EXAMPLES: tuple[
    tuple[str, Mapping[str, object], tuple[int, ...], int, RiskLevel], ...
] = (
    (
        "S1",
        customer_data(),
        (150, 150, 200, 200, 100, 135),
        935,
        RiskLevel.LOW,
    ),
    (
        "S2",
        customer_data(
            monthly_income=5_000,
            monthly_debt_payment=2_500,
            employment_months=60,
            credit_history_months=120,
            delinquency_count_12m=1,
            inquiry_count_6m=2,
            requested_amount=30_000,
        ),
        (75, 75, 125, 160, 80, 75),
        590,
        RiskLevel.MEDIUM,
    ),
    (
        "S3",
        customer_data(
            monthly_income=4_000,
            monthly_debt_payment=4_000,
            employment_months=0,
            credit_history_months=0,
            delinquency_count_12m=5,
            inquiry_count_6m=10,
            requested_amount=48_000,
        ),
        (0, 0, 0, 0, 0, 0),
        0,
        RiskLevel.HIGH,
    ),
    (
        "S4",
        customer_data(
            monthly_income=5_000,
            monthly_debt_payment=2_000,
            employment_months=120,
            credit_history_months=240,
            delinquency_count_12m=1,
            inquiry_count_6m=2,
            requested_amount=36_000,
        ),
        (150, 150, 150, 160, 80, 60),
        750,
        RiskLevel.LOW,
    ),
    (
        "S5",
        customer_data(
            monthly_income=5_000,
            monthly_debt_payment=2_500,
            employment_months=60,
            credit_history_months=120,
            delinquency_count_12m=2,
            inquiry_count_6m=4,
            requested_amount=42_400,
        ),
        (75, 75, 125, 120, 60, 44),
        499,
        RiskLevel.HIGH,
    ),
)


@pytest.mark.parametrize(
    ("example_id", "raw", "contributions", "expected_score", "expected_level"),
    FROZEN_SCORE_EXAMPLES,
)
def test_frozen_scoring_examples(
    example_id: str,
    raw: Mapping[str, object],
    contributions: tuple[int, ...],
    expected_score: int,
    expected_level: RiskLevel,
) -> None:
    result = RiskModelTool().score(raw)

    assert result.success, example_id
    assert tuple(
        factor.rounded_contribution for factor in result.factors
    ) == contributions
    assert result.score == expected_score
    assert result.risk_level is expected_level
    assert result.score == sum(contributions)


@pytest.mark.parametrize(
    ("requested_amount", "expected_score", "expected_level"),
    [
        (42_400, 499, RiskLevel.HIGH),
        (42_000, 500, RiskLevel.MEDIUM),
        (36_400, 749, RiskLevel.MEDIUM),
        (36_000, 750, RiskLevel.LOW),
    ],
)
def test_score_level_boundaries(
    requested_amount: int,
    expected_score: int,
    expected_level: RiskLevel,
) -> None:
    raw = customer_data(
        monthly_income=5_000,
        monthly_debt_payment=2_500 if expected_score <= 500 else 2_000,
        employment_months=60 if expected_score <= 500 else 120,
        credit_history_months=120 if expected_score <= 500 else 240,
        delinquency_count_12m=2 if expected_score <= 500 else 1,
        inquiry_count_6m=4 if expected_score <= 500 else 2,
        requested_amount=requested_amount,
    )

    result = RiskModelTool().score(raw)

    assert result.score == expected_score
    assert result.risk_level is expected_level


def test_round_half_up_and_decimal_precision() -> None:
    result = RiskModelTool().score(customer(employment_months=2))
    employment = result.factors[0]

    assert employment.raw_contribution == "2.5"
    assert employment.rounded_contribution == 3
    assert result.evidence[0].calculation_trace.endswith("ROUND_HALF_UP=3")


def test_each_contribution_stays_within_frozen_bounds_and_sums_to_score() -> None:
    maximum = RiskModelTool().score(
        customer(
            monthly_income=100_000,
            monthly_debt_payment=0,
            employment_months=600,
            credit_history_months=600,
            delinquency_count_12m=0,
            inquiry_count_6m=0,
            requested_amount=1_000,
        )
    )
    minimum = RiskModelTool().score(
        customer(
            monthly_income=4_000,
            monthly_debt_payment=100_000,
            employment_months=0,
            credit_history_months=0,
            delinquency_count_12m=12,
            inquiry_count_6m=20,
            requested_amount=500_000,
        )
    )

    for result in (maximum, minimum):
        assert result.score == sum(
            factor.rounded_contribution for factor in result.factors
        )
        assert all(
            0 <= factor.rounded_contribution <= factor.max_contribution
            for factor in result.factors
        )
    assert maximum.score == 1_000
    assert minimum.score == 0


@pytest.mark.parametrize(
    ("overrides", "rule_id", "expected"),
    [
        ({"verified_identity": True}, "R001", False),
        ({"verified_identity": False}, "R001", True),
        ({"delinquency_count_12m": 2}, "R002", False),
        ({"delinquency_count_12m": 3}, "R002", True),
        (
            {"monthly_income": 5_000, "monthly_debt_payment": 3_999},
            "R003",
            False,
        ),
        (
            {"monthly_income": 5_000, "monthly_debt_payment": 4_000},
            "R003",
            True,
        ),
        (
            {"monthly_income": 5_000, "requested_amount": 60_000},
            "R004",
            False,
        ),
        (
            {"monthly_income": 5_000, "requested_amount": 60_001},
            "R004",
            True,
        ),
    ],
)
def test_each_rule_hit_and_boundary_behavior(
    overrides: Mapping[str, object],
    rule_id: str,
    expected: bool,
) -> None:
    result = RuleEngineTool().evaluate(customer(**dict(overrides)))
    execution = next(item for item in result.executions if item.rule_id == rule_id)

    assert execution.matched is expected
    assert execution.result is (
        RuleResult.REJECT_CANDIDATE if expected else RuleResult.NO_ACTION
    )


def test_all_four_rules_execute_without_short_circuit() -> None:
    result = RuleEngineTool().evaluate(
        customer(
            verified_identity=False,
            monthly_income=5_000,
            monthly_debt_payment=4_000,
            delinquency_count_12m=3,
            requested_amount=60_001,
        )
    )

    assert result.success
    assert result.total_rule_count == 4
    assert result.matched_rule_count == 4
    assert tuple(item.rule_id for item in result.executions) == (
        "R001",
        "R002",
        "R003",
        "R004",
    )
    assert all(item.matched for item in result.executions)


def test_rule_and_model_evidence_is_pending_and_traceable() -> None:
    snapshot = customer()
    rule_result = RuleEngineTool().evaluate(snapshot)
    score_result = RiskModelTool().score(snapshot)

    assert len(rule_result.evidence) == 4
    assert len(score_result.evidence) == 8
    for item in (*rule_result.evidence, *score_result.evidence):
        assert item.customer_id == snapshot.customer_id
        assert item.data_version == snapshot.data_version
        assert item.validation_status == "PENDING"
        assert item.evidence_id
        assert item.field_path.startswith("/")
        assert item.calculation_trace
    assert all(item.rule_version == DEMO_RULE_VERSION for item in rule_result.evidence)
    assert all(
        item.model_version == DEMO_MODEL_VERSION for item in score_result.evidence
    )


def test_same_input_and_version_is_reproducible() -> None:
    snapshot = customer()

    assert RuleEngineTool().evaluate(snapshot) == RuleEngineTool().evaluate(snapshot)
    assert RiskModelTool().score(snapshot) == RiskModelTool().score(snapshot)


@pytest.mark.parametrize("bad_income", [0, -1, "5000"])
def test_tools_fail_closed_for_invalid_income(bad_income: object) -> None:
    raw = customer_data(monthly_income=bad_income)
    rule_result = RuleEngineTool().evaluate(raw)
    score_result = RiskModelTool().score(raw)

    assert not rule_result.success
    assert not score_result.success
    assert rule_result.executions == ()
    assert score_result.factors == ()
    assert rule_result.errors[0].code is ToolErrorCode.DATA_CONTRACT_VIOLATION
    assert score_result.errors[0].code is ToolErrorCode.DATA_CONTRACT_VIOLATION


def test_tools_fail_closed_for_missing_required_field() -> None:
    raw = customer_data()
    del raw["monthly_income"]

    rule_result = RuleEngineTool().evaluate(raw)
    score_result = RiskModelTool().score(raw)

    assert not rule_result.success
    assert not score_result.success
    assert rule_result.errors[0].code is ToolErrorCode.REQUIRED_FIELD_MISSING
    assert score_result.errors[0].code is ToolErrorCode.REQUIRED_FIELD_MISSING


def test_unknown_versions_are_rejected() -> None:
    snapshot = customer()
    rule_result = RuleEngineTool().evaluate(snapshot, rule_version="unknown")
    score_result = RiskModelTool().score(snapshot, model_version="unknown")

    assert rule_result.errors[0].code is ToolErrorCode.RULE_VERSION_UNSUPPORTED
    assert score_result.errors[0].code is ToolErrorCode.MODEL_VERSION_UNSUPPORTED


def test_tools_do_not_access_network_or_external_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    snapshot = customer()

    assert RuleEngineTool().evaluate(snapshot).success
    assert RiskModelTool().score(snapshot).success

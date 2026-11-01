"""Structured, fixed-template explanation contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from creditpilot.models.decision import DecisionStatus
from creditpilot.models.risk import RiskLevel

TEMPLATE_VERSION = "explanation-templates-v1"


class PolicyReasonExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    reason_id: str
    source_type: Literal["RULE", "SCORE_POLICY"]
    source_id: str
    condition: str
    actual_value: JsonValue
    text: str
    evidence_ids: tuple[str, ...]


class ModelFactorExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    factor_id: str
    contribution: int
    max_contribution: int
    text: str
    evidence_ids: tuple[str, ...]


class BusinessGuidanceExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    template_id: str
    text: str
    review_actions: tuple[str, ...]
    limitation: str


class StructuredExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    template_version: Literal["explanation-templates-v1"] = TEMPLATE_VERSION
    customer_id: str
    data_version: str
    rule_version: str
    model_version: str
    decision_status: DecisionStatus
    summary: str
    score: int
    risk_level: RiskLevel
    score_threshold_met: bool
    matched_rule_ids: tuple[str, ...]
    rule_total: int
    policy_decision_reasons: tuple[PolicyReasonExplanation, ...]
    model_risk_factors: tuple[ModelFactorExplanation, ...]
    business_guidance: BusinessGuidanceExplanation
    evidence_ids: tuple[str, ...]


class ReviewExplanation(BaseModel):
    """Fact-free fixed response when no deterministic conclusion is publishable."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    template_version: Literal["explanation-templates-v1"] = TEMPLATE_VERSION
    customer_id: str | None
    decision_status: DecisionStatus
    summary: str
    business_guidance: BusinessGuidanceExplanation
    evidence_ids: tuple[()] = ()


class StageBValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    report_id: str
    stage: Literal["B"] = "B"
    status: Literal["CONSISTENT", "INCONSISTENT"]
    issue_codes: tuple[str, ...]
    blocked_output: Literal["NONE", "CANDIDATE_EXPLANATION"]

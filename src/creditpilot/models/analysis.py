"""Public contracts for deterministic offline analysis."""

import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from creditpilot.models.customer import CustomerId
from creditpilot.models.decision import (
    AnalysisStatus,
    BusinessGuidanceContract,
    DecisionStatus,
    EvidenceReference,
    PolicyDecisionReason,
)
from creditpilot.models.explanation import ReviewExplanation, StructuredExplanation
from creditpilot.models.risk import ModelRiskFactor, RiskLevel, RuleExecution

CONTRACT_VERSION = "analysis-contract-v1"
DISCLAIMER = (
    "Synthetic demonstration only; not a real credit approval, decline, "
    "credit limit decision, or prediction of default."
)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    customer_id: CustomerId
    question: str = Field(min_length=1, max_length=500)
    mode: Literal["rules", "llm"]

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 500:
            raise ValueError("question must contain 1 to 500 non-space characters")
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", normalized):
            raise ValueError("question contains unsupported control characters")
        return normalized


class AnalysisVersions(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    data_version: str | None = None
    rule_version: str | None = None
    model_version: str | None = None
    strategy_version: str | None = None
    contract_version: str = CONTRACT_VERSION


class RuleSummary(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    total: int
    matched: int
    executions: tuple[RuleExecution, ...]


class RiskScore(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    score: int = Field(ge=0, le=1_000)
    level: RiskLevel
    factors: tuple[ModelRiskFactor, ...]


class ScorePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    condition_id: Literal["P_SCORE_001"] = "P_SCORE_001"
    threshold: int = 500
    operator: Literal["<"] = "<"
    condition_triggered: bool
    pass_threshold_met: bool
    evidence_ids: tuple[str, ...]


class ValidationSummary(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    report_id: str
    stage: Literal["A", "B"] = "A"
    status: str
    issue_codes: tuple[str, ...]


class AnalysisError(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    code: str
    message: str
    source: str


class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    request_id: UUID
    analysis_status: AnalysisStatus
    decision_status: DecisionStatus
    customer_id: str | None
    data_version: str | None = None
    rule_version: str | None = None
    model_version: str | None = None
    versions: AnalysisVersions
    score: int | None = None
    risk_level: RiskLevel | None = None
    rule_results: tuple[RuleExecution, ...] = ()
    rule_summary: RuleSummary | None = None
    risk_score: RiskScore | None = None
    score_policy: ScorePolicy | None = None
    policy_reasons: tuple[PolicyDecisionReason, ...] = ()
    policy_decision_reasons: tuple[PolicyDecisionReason, ...] = ()
    model_risk_factors: tuple[ModelRiskFactor, ...] = ()
    business_guidance: BusinessGuidanceContract | None = None
    explanation: StructuredExplanation | ReviewExplanation | None = None
    evidence_references: tuple[EvidenceReference, ...] = ()
    validation_reports: tuple[ValidationSummary, ...] = ()
    errors: tuple[AnalysisError, ...] = ()
    error_code: str | None = None
    degradation: None = None
    disclaimer: str = DISCLAIMER

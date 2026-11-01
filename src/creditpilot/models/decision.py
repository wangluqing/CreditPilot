"""Frozen stage-A evidence and deterministic decision contracts."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from creditpilot.models.risk import ModelRiskFactor, ToolErrorCode

STRATEGY_VERSION = "demo-policy-v1"


class AnalysisStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NOT_FOUND = "NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"


class DecisionStatus(StrEnum):
    PASS = "PASS"
    REJECT = "REJECT"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_EVALUATED = "NOT_EVALUATED"


class EvidenceStatus(StrEnum):
    PENDING = "PENDING"
    VALID = "VALID"
    MISSING = "MISSING"
    CONFLICT = "CONFLICT"
    STALE = "STALE"
    INVALID_SOURCE = "INVALID_SOURCE"


class ValidationReportStatus(StrEnum):
    CONSISTENT = "CONSISTENT"
    INCONSISTENT = "INCONSISTENT"


class EvidenceReference(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    evidence_id: str
    source_tool: str
    validation_status: EvidenceStatus


class ValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    error_code: ToolErrorCode
    field_path: str
    detail: str
    evidence_ids: tuple[str, ...] = ()


class ValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    report_id: str
    stage: Literal["A"] = "A"
    customer_id: str
    data_version: str
    rule_version: str
    model_version: str
    status: ValidationReportStatus
    issues: tuple[ValidationIssue, ...]
    evidence_references: tuple[EvidenceReference, ...]
    validated_evidence_ids: tuple[str, ...]
    rule_result_digest: str
    model_result_digest: str
    blocked_conclusions: tuple[str, ...] = ()


class PolicyDecisionReason(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    reason_id: str
    source_type: Literal["RULE", "SCORE_POLICY"]
    source_id: str
    condition: str
    strategy_version: Literal["demo-policy-v1"] = STRATEGY_VERSION
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class BusinessGuidanceContract(BaseModel):
    """Template references only; no generated or LLM-authored guidance."""

    model_config = ConfigDict(frozen=True, strict=True)
    template_ids: tuple[str, ...]
    rendering_status: Literal["NOT_RENDERED"] = "NOT_RENDERED"


class StructuredDecisionResult(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    customer_id: str
    data_version: str
    rule_version: str
    model_version: str
    strategy_version: Literal["demo-policy-v1"] = STRATEGY_VERSION
    analysis_status: AnalysisStatus
    decision_status: DecisionStatus
    validation_report: ValidationReport
    policy_reasons: tuple[PolicyDecisionReason, ...]
    model_risk_factors: tuple[ModelRiskFactor, ...]
    business_guidance: BusinessGuidanceContract
    evidence_references: tuple[EvidenceReference, ...]
    error_code: ToolErrorCode | None = None

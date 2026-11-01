"""Structured contracts for deterministic demo rules and scoring."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictInt

DEMO_RULE_VERSION = "demo-rules-v1"
DEMO_MODEL_VERSION = "demo-score-v1"


class ToolErrorCode(StrEnum):
    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    DATA_CONTRACT_VIOLATION = "DATA_CONTRACT_VIOLATION"
    RULE_VERSION_UNSUPPORTED = "RULE_VERSION_UNSUPPORTED"
    MODEL_VERSION_UNSUPPORTED = "MODEL_VERSION_UNSUPPORTED"
    RULE_EXECUTION_FAILED = "RULE_EXECUTION_FAILED"
    SCORE_CALCULATION_FAILED = "SCORE_CALCULATION_FAILED"
    SCORE_INVARIANT_VIOLATION = "SCORE_INVARIANT_VIOLATION"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RuleResult(StrEnum):
    REJECT_CANDIDATE = "REJECT_CANDIDATE"
    NO_ACTION = "NO_ACTION"


class PendingEvidence(BaseModel):
    """Evidence awaiting the later, separate EvidenceValidator stage."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    evidence_id: str
    source_tool: Literal["RuleEngineTool", "RiskModelTool"]
    customer_id: str
    data_version: str
    rule_version: str | None = None
    model_version: str | None = None
    field_path: str
    actual_value: JsonValue
    calculation_trace: str
    validation_status: Literal["PENDING"] = "PENDING"


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: ToolErrorCode
    message: str
    source_tool: Literal["RuleEngineTool", "RiskModelTool"]
    retryable: StrictBool = False
    details: dict[str, JsonValue] | None = None


class RuleExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    rule_id: Literal["R001", "R002", "R003", "R004"]
    rule_version: Literal["demo-rules-v1"]
    sequence: StrictInt = Field(ge=1, le=4)
    field_paths: tuple[str, ...]
    operator: Literal["==", ">=", ">"]
    threshold: JsonValue
    actual_value: JsonValue
    matched: StrictBool
    result: RuleResult
    evidence_ids: tuple[str, ...]


class RuleEngineResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    success: StrictBool
    customer_id: str | None = None
    data_version: str | None = None
    rule_version: str
    total_rule_count: StrictInt = 0
    matched_rule_count: StrictInt = 0
    executions: tuple[RuleExecution, ...] = ()
    evidence: tuple[PendingEvidence, ...] = ()
    errors: tuple[ToolError, ...] = ()


class ModelRiskFactor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    factor_id: Literal[
        "F_EMPLOYMENT",
        "F_HISTORY",
        "F_DEBT_LOAD",
        "F_DELINQUENCY",
        "F_INQUIRY",
        "F_AFFORDABILITY",
    ]
    raw_contribution: str
    rounded_contribution: StrictInt
    max_contribution: StrictInt
    direction: str
    formula_id: str
    evidence_ids: tuple[str, ...]


class RiskModelResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    success: StrictBool
    customer_id: str | None = None
    data_version: str | None = None
    model_version: str
    score: StrictInt | None = Field(default=None, ge=0, le=1_000)
    risk_level: RiskLevel | None = None
    factors: tuple[ModelRiskFactor, ...] = ()
    evidence: tuple[PendingEvidence, ...] = ()
    errors: tuple[ToolError, ...] = ()
    disclaimer: str = (
        "Synthetic demo score only; not a default probability or real prediction."
    )


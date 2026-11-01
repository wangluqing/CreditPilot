"""Exact, read-only access to versioned synthetic customer snapshots."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from creditpilot.models.customer import (
    DATA_VERSION,
    CustomerId,
    CustomerRecord,
    SyntheticDataset,
)

REQUIRED_FIELDS = frozenset(
    name
    for name, field in CustomerRecord.model_fields.items()
    if field.is_required()
)
OPTIONAL_FIELDS = frozenset(CustomerRecord.model_fields) - REQUIRED_FIELDS


class AnalysisStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NOT_FOUND = "NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"


class EvidenceStatus(StrEnum):
    PENDING = "PENDING"


class CustomerErrorCode(StrEnum):
    INVALID_CUSTOMER_ID = "INVALID_CUSTOMER_ID"
    CUSTOMER_NOT_FOUND = "CUSTOMER_NOT_FOUND"
    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    DATA_CONTRACT_VIOLATION = "DATA_CONTRACT_VIOLATION"
    DATA_VERSION_MISMATCH = "DATA_VERSION_MISMATCH"


class CustomerEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    evidence_id: str
    source_tool: str = "CustomerTool"
    customer_id: str
    data_version: str
    field_path: str
    value: JsonValue
    validation_status: EvidenceStatus = EvidenceStatus.PENDING


class CustomerToolError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: CustomerErrorCode
    message: str
    source_tool: str = "CustomerTool"
    retryable: bool = False
    details: dict[str, JsonValue] | None = None


class CustomerToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    analysis_status: AnalysisStatus
    customer: CustomerRecord | None = None
    data_version: str | None = None
    field_availability: dict[str, bool] = Field(default_factory=dict)
    missing_required_fields: tuple[str, ...] = ()
    missing_optional_fields: tuple[str, ...] = ()
    evidence: tuple[CustomerEvidence, ...] = ()
    errors: tuple[CustomerToolError, ...] = ()


class CustomerLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    customer_id: CustomerId
    expected_data_version: str


def _evidence_id(customer_id: str, field_path: str, value: JsonValue) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    content = f"CustomerTool|{customer_id}|{DATA_VERSION}|{field_path}|{serialized}"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return f"EV-CUSTOMER-{digest}"


class CustomerTool:
    """Read synthetic customers by exact ID without network or downstream tools."""

    def __init__(self, records: Sequence[Mapping[str, Any]]) -> None:
        self._records: dict[str, Mapping[str, Any]] = {}
        for record in records:
            customer_id = record.get("customer_id")
            if isinstance(customer_id, str):
                if customer_id in self._records:
                    raise ValueError(f"duplicate customer_id: {customer_id}")
                self._records[customer_id] = dict(record)

    @classmethod
    def from_dataset(cls, dataset: SyntheticDataset) -> "CustomerTool":
        return cls(
            [customer.model_dump(mode="python") for customer in dataset.customers]
        )

    @classmethod
    def from_json(cls, path: Path) -> "CustomerTool":
        dataset = SyntheticDataset.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        return cls.from_dataset(dataset)

    @classmethod
    def from_default_dataset(cls) -> "CustomerTool":
        project_root = Path(__file__).resolve().parents[3]
        return cls.from_json(
            project_root / "data" / "synthetic" / "customers_v1.json"
        )

    def lookup(
        self,
        customer_id: object,
        *,
        expected_data_version: object = DATA_VERSION,
    ) -> CustomerToolResult:
        try:
            request = CustomerLookupRequest.model_validate(
                {
                    "customer_id": customer_id,
                    "expected_data_version": expected_data_version,
                }
            )
        except ValidationError:
            return CustomerToolResult(
                analysis_status=AnalysisStatus.INVALID_INPUT,
                errors=(
                    CustomerToolError(
                        code=CustomerErrorCode.INVALID_CUSTOMER_ID,
                        message="customer_id must match the synthetic ID format",
                    ),
                ),
            )

        if request.expected_data_version != DATA_VERSION:
            return CustomerToolResult(
                analysis_status=AnalysisStatus.FAILED,
                errors=(
                    CustomerToolError(
                        code=CustomerErrorCode.DATA_VERSION_MISMATCH,
                        message="requested synthetic data version is unsupported",
                    ),
                ),
            )

        raw = self._records.get(request.customer_id)
        if raw is None:
            return CustomerToolResult(
                analysis_status=AnalysisStatus.NOT_FOUND,
                errors=(
                    CustomerToolError(
                        code=CustomerErrorCode.CUSTOMER_NOT_FOUND,
                        message="synthetic customer was not found",
                    ),
                ),
            )

        present = frozenset(raw)
        missing_required = tuple(sorted(REQUIRED_FIELDS - present))
        missing_optional = tuple(sorted(OPTIONAL_FIELDS - present))
        availability = {
            field: field in present for field in CustomerRecord.model_fields
        }
        if missing_required:
            return CustomerToolResult(
                analysis_status=AnalysisStatus.PARTIAL,
                data_version=_safe_data_version(raw),
                field_availability=availability,
                missing_required_fields=missing_required,
                missing_optional_fields=missing_optional,
                errors=(
                    CustomerToolError(
                        code=CustomerErrorCode.REQUIRED_FIELD_MISSING,
                        message="required synthetic customer fields are missing",
                        details={"fields": list(missing_required)},
                    ),
                ),
            )

        if raw.get("data_version") != request.expected_data_version:
            return CustomerToolResult(
                analysis_status=AnalysisStatus.FAILED,
                data_version=_safe_data_version(raw),
                field_availability=availability,
                missing_optional_fields=missing_optional,
                errors=(
                    CustomerToolError(
                        code=CustomerErrorCode.DATA_VERSION_MISMATCH,
                        message="synthetic customer data version is unsupported",
                    ),
                ),
            )

        try:
            customer = CustomerRecord.model_validate(raw)
        except ValidationError:
            return CustomerToolResult(
                analysis_status=AnalysisStatus.FAILED,
                data_version=_safe_data_version(raw),
                field_availability=availability,
                missing_optional_fields=missing_optional,
                errors=(
                    CustomerToolError(
                        code=CustomerErrorCode.DATA_CONTRACT_VIOLATION,
                        message="synthetic customer violates the frozen data contract",
                    ),
                ),
            )

        evidence = tuple(
            CustomerEvidence(
                evidence_id=_evidence_id(
                    customer.customer_id,
                    f"/{field}",
                    value,
                ),
                customer_id=customer.customer_id,
                data_version=customer.data_version,
                field_path=f"/{field}",
                value=value,
            )
            for field, value in customer.model_dump(mode="json").items()
            if field in present
        )
        return CustomerToolResult(
            analysis_status=AnalysisStatus.SUCCESS,
            customer=customer,
            data_version=customer.data_version,
            field_availability=availability,
            missing_optional_fields=missing_optional,
            evidence=evidence,
        )
def _safe_data_version(record: Mapping[str, Any]) -> str | None:
    value = record.get("data_version")
    return value if isinstance(value, str) else None

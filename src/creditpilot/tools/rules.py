"""Deterministic execution of the four frozen synthetic demo rules."""

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from creditpilot.models.customer import CustomerRecord
from creditpilot.models.risk import (
    DEMO_RULE_VERSION,
    PendingEvidence,
    RuleEngineResult,
    RuleExecution,
    RuleResult,
    ToolError,
    ToolErrorCode,
)


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _evidence_id(
    customer: CustomerRecord,
    rule_id: str,
    field_path: str,
    actual_value: object,
) -> str:
    value = json.dumps(actual_value, ensure_ascii=False, sort_keys=True)
    content = (
        f"RuleEngineTool|{customer.customer_id}|{customer.data_version}|"
        f"{DEMO_RULE_VERSION}|{rule_id}|{field_path}|{value}"
    )
    return f"EV-RULE-{hashlib.sha256(content.encode()).hexdigest()[:16]}"


def _customer_or_error(
    customer: CustomerRecord | Mapping[str, Any],
) -> tuple[CustomerRecord | None, ToolError | None]:
    if isinstance(customer, CustomerRecord):
        return customer, None
    try:
        return CustomerRecord.model_validate(customer), None
    except ValidationError as exc:
        missing = sorted(
            str(error["loc"][0])
            for error in exc.errors()
            if error["type"] == "missing"
        )
        code = (
            ToolErrorCode.REQUIRED_FIELD_MISSING
            if missing
            else ToolErrorCode.DATA_CONTRACT_VIOLATION
        )
        return None, ToolError(
            code=code,
            message="customer input cannot be evaluated by the frozen rules",
            source_tool="RuleEngineTool",
            details={"fields": missing} if missing else None,
        )


class RuleEngineTool:
    """Pure rule evaluation; it never produces a final policy decision."""

    def evaluate(
        self,
        customer: CustomerRecord | Mapping[str, Any],
        *,
        rule_version: str = DEMO_RULE_VERSION,
    ) -> RuleEngineResult:
        if rule_version != DEMO_RULE_VERSION:
            return RuleEngineResult(
                success=False,
                rule_version=rule_version,
                errors=(
                    ToolError(
                        code=ToolErrorCode.RULE_VERSION_UNSUPPORTED,
                        message="rule version is unsupported",
                        source_tool="RuleEngineTool",
                    ),
                ),
            )

        snapshot, error = _customer_or_error(customer)
        if snapshot is None:
            return RuleEngineResult(
                success=False,
                rule_version=rule_version,
                errors=(error,) if error else (),
            )

        debt_ratio = Decimal(snapshot.monthly_debt_payment) / Decimal(
            snapshot.monthly_income
        )
        request_ratio = Decimal(snapshot.requested_amount) / (
            Decimal(12) * Decimal(snapshot.monthly_income)
        )
        specifications: tuple[
            tuple[str, tuple[str, ...], str, object, object, bool, str], ...
        ] = (
            (
                "R001",
                ("/verified_identity",),
                "==",
                False,
                snapshot.verified_identity,
                snapshot.verified_identity is False,
                "verified_identity == false",
            ),
            (
                "R002",
                ("/delinquency_count_12m",),
                ">=",
                3,
                snapshot.delinquency_count_12m,
                snapshot.delinquency_count_12m >= 3,
                "delinquency_count_12m >= 3",
            ),
            (
                "R003",
                ("/monthly_debt_payment", "/monthly_income"),
                ">=",
                "0.80",
                _decimal_text(debt_ratio),
                debt_ratio >= Decimal("0.80"),
                "Decimal(monthly_debt_payment) / Decimal(monthly_income)",
            ),
            (
                "R004",
                ("/requested_amount", "/monthly_income"),
                ">",
                "1.00",
                _decimal_text(request_ratio),
                request_ratio > Decimal("1.00"),
                "Decimal(requested_amount) / (Decimal(12) * Decimal(monthly_income))",
            ),
        )

        executions: list[RuleExecution] = []
        evidence: list[PendingEvidence] = []
        derived_paths = {
            "R003": "/derived/debt_to_income_ratio",
            "R004": "/derived/request_to_annual_income_ratio",
        }
        for sequence, (
            rule_id,
            field_paths,
            operator,
            threshold,
            actual_value,
            matched,
            trace,
        ) in enumerate(specifications, start=1):
            field_path = (
                field_paths[0]
                if len(field_paths) == 1
                else derived_paths[rule_id]
            )
            evidence_id = _evidence_id(
                snapshot,
                rule_id,
                field_path,
                actual_value,
            )
            evidence.append(
                PendingEvidence(
                    evidence_id=evidence_id,
                    source_tool="RuleEngineTool",
                    customer_id=snapshot.customer_id,
                    data_version=snapshot.data_version,
                    rule_version=DEMO_RULE_VERSION,
                    field_path=field_path,
                    actual_value=actual_value,
                    calculation_trace=trace,
                )
            )
            executions.append(
                RuleExecution(
                    rule_id=rule_id,
                    rule_version=DEMO_RULE_VERSION,
                    sequence=sequence,
                    field_paths=field_paths,
                    operator=operator,
                    threshold=threshold,
                    actual_value=actual_value,
                    matched=matched,
                    result=(
                        RuleResult.REJECT_CANDIDATE
                        if matched
                        else RuleResult.NO_ACTION
                    ),
                    evidence_ids=(evidence_id,),
                )
            )

        matched_count = sum(execution.matched for execution in executions)
        return RuleEngineResult(
            success=True,
            customer_id=snapshot.customer_id,
            data_version=snapshot.data_version,
            rule_version=DEMO_RULE_VERSION,
            total_rule_count=len(executions),
            matched_rule_count=matched_count,
            executions=tuple(executions),
            evidence=tuple(evidence),
        )

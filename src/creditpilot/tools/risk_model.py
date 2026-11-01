"""Transparent deterministic implementation of demo-score-v1."""

import hashlib
import json
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import ValidationError

from creditpilot.models.customer import CustomerRecord
from creditpilot.models.risk import (
    DEMO_MODEL_VERSION,
    ModelRiskFactor,
    PendingEvidence,
    RiskLevel,
    RiskModelResult,
    ToolError,
    ToolErrorCode,
)

ONE = Decimal(1)
ZERO = Decimal(0)


def _clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    return max(lower, min(value, upper))


def _round_contribution(value: Decimal) -> int:
    return int(value.quantize(ONE, rounding=ROUND_HALF_UP))


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _evidence_id(
    customer: CustomerRecord,
    field_path: str,
    actual_value: object,
    trace: str,
) -> str:
    value = json.dumps(actual_value, ensure_ascii=False, sort_keys=True)
    content = (
        f"RiskModelTool|{customer.customer_id}|{customer.data_version}|"
        f"{DEMO_MODEL_VERSION}|{field_path}|{value}|{trace}"
    )
    return f"EV-MODEL-{hashlib.sha256(content.encode()).hexdigest()[:16]}"


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
            message="customer input cannot be evaluated by the demo score",
            source_tool="RiskModelTool",
            details={"fields": missing} if missing else None,
        )


class RiskModelTool:
    """Pure Decimal scoring with no network, randomness, or LLM dependency."""

    def score(
        self,
        customer: CustomerRecord | Mapping[str, Any],
        *,
        model_version: str = DEMO_MODEL_VERSION,
    ) -> RiskModelResult:
        if model_version != DEMO_MODEL_VERSION:
            return RiskModelResult(
                success=False,
                model_version=model_version,
                errors=(
                    ToolError(
                        code=ToolErrorCode.MODEL_VERSION_UNSUPPORTED,
                        message="model version is unsupported",
                        source_tool="RiskModelTool",
                    ),
                ),
            )

        snapshot, error = _customer_or_error(customer)
        if snapshot is None:
            return RiskModelResult(
                success=False,
                model_version=model_version,
                errors=(error,) if error else (),
            )

        income = Decimal(snapshot.monthly_income)
        debt_ratio = Decimal(snapshot.monthly_debt_payment) / income
        request_ratio = Decimal(snapshot.requested_amount) / (Decimal(12) * income)

        definitions: tuple[
            tuple[str, Decimal, Decimal, str, str, str], ...
        ] = (
            (
                "F_EMPLOYMENT",
                Decimal(150)
                * min(Decimal(snapshot.employment_months) / Decimal(120), ONE),
                Decimal(150),
                "higher employment months never lower the contribution",
                "E_V1",
                "150 * min(employment_months / 120, 1)",
            ),
            (
                "F_HISTORY",
                Decimal(150)
                * min(Decimal(snapshot.credit_history_months) / Decimal(240), ONE),
                Decimal(150),
                "longer history never lowers the contribution",
                "H_V1",
                "150 * min(credit_history_months / 240, 1)",
            ),
            (
                "F_DEBT_LOAD",
                Decimal(250) * (ONE - min(debt_ratio, ONE)),
                Decimal(250),
                "higher debt ratio never raises the contribution",
                "D_V1",
                "250 * (1 - min(monthly_debt_payment / monthly_income, 1))",
            ),
            (
                "F_DELINQUENCY",
                Decimal(200)
                * max(
                    ZERO,
                    ONE - Decimal(snapshot.delinquency_count_12m) / Decimal(5),
                ),
                Decimal(200),
                "more delinquencies never raise the contribution",
                "L_V1",
                "200 * max(0, 1 - delinquency_count_12m / 5)",
            ),
            (
                "F_INQUIRY",
                Decimal(100)
                * max(
                    ZERO,
                    ONE - Decimal(snapshot.inquiry_count_6m) / Decimal(10),
                ),
                Decimal(100),
                "more inquiries never raise the contribution",
                "Q_V1",
                "100 * max(0, 1 - inquiry_count_6m / 10)",
            ),
            (
                "F_AFFORDABILITY",
                Decimal(150) * (ONE - min(request_ratio, ONE)),
                Decimal(150),
                "higher request ratio never raises the contribution",
                "A_V1",
                "150 * (1 - min(requested_amount / (12 * monthly_income), 1))",
            ),
        )

        factors: list[ModelRiskFactor] = []
        evidence: list[PendingEvidence] = []
        for factor_id, raw, maximum, direction, formula_id, trace in definitions:
            clamped = _clamp(raw, ZERO, maximum)
            rounded = _round_contribution(clamped)
            field_path = f"/result/factors/{factor_id}/rounded_contribution"
            evidence_id = _evidence_id(snapshot, field_path, rounded, trace)
            evidence.append(
                PendingEvidence(
                    evidence_id=evidence_id,
                    source_tool="RiskModelTool",
                    customer_id=snapshot.customer_id,
                    data_version=snapshot.data_version,
                    model_version=DEMO_MODEL_VERSION,
                    field_path=field_path,
                    actual_value=rounded,
                    calculation_trace=(
                        f"{trace}; raw={_decimal_text(raw)}; "
                        f"clamped={_decimal_text(clamped)}; ROUND_HALF_UP={rounded}"
                    ),
                )
            )
            factors.append(
                ModelRiskFactor(
                    factor_id=factor_id,
                    raw_contribution=_decimal_text(clamped),
                    rounded_contribution=rounded,
                    max_contribution=int(maximum),
                    direction=direction,
                    formula_id=formula_id,
                    evidence_ids=(evidence_id,),
                )
            )

        score = sum(factor.rounded_contribution for factor in factors)
        if not 0 <= score <= 1_000:
            return RiskModelResult(
                success=False,
                customer_id=snapshot.customer_id,
                data_version=snapshot.data_version,
                model_version=DEMO_MODEL_VERSION,
                errors=(
                    ToolError(
                        code=ToolErrorCode.SCORE_INVARIANT_VIOLATION,
                        message="demo score is outside the frozen range",
                        source_tool="RiskModelTool",
                    ),
                ),
            )

        level = (
            RiskLevel.LOW
            if score >= 750
            else RiskLevel.MEDIUM
            if score >= 500
            else RiskLevel.HIGH
        )
        for field_path, value, trace in (
            (
                "/result/score",
                score,
                "sum of six independently rounded contributions",
            ),
            (
                "/result/risk_level",
                level.value,
                "LOW >= 750; MEDIUM >= 500; otherwise HIGH",
            ),
        ):
            evidence_id = _evidence_id(snapshot, field_path, value, trace)
            evidence.append(
                PendingEvidence(
                    evidence_id=evidence_id,
                    source_tool="RiskModelTool",
                    customer_id=snapshot.customer_id,
                    data_version=snapshot.data_version,
                    model_version=DEMO_MODEL_VERSION,
                    field_path=field_path,
                    actual_value=value,
                    calculation_trace=trace,
                )
            )

        return RiskModelResult(
            success=True,
            customer_id=snapshot.customer_id,
            data_version=snapshot.data_version,
            model_version=DEMO_MODEL_VERSION,
            score=score,
            risk_level=level,
            factors=tuple(factors),
            evidence=tuple(evidence),
        )


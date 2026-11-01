"""Stage-A validation of deterministic tool evidence; never repairs inputs."""

import hashlib
import json
import weakref
from collections import Counter
from typing import Any

from creditpilot.models.customer import CustomerRecord
from creditpilot.models.decision import (
    EvidenceReference,
    EvidenceStatus,
    StructuredDecisionResult,
    ValidationIssue,
    ValidationReport,
    ValidationReportStatus,
)
from creditpilot.models.explanation import (
    StageBValidationReport,
    StructuredExplanation,
)
from creditpilot.models.risk import (
    DEMO_MODEL_VERSION,
    DEMO_RULE_VERSION,
    RiskModelResult,
    RuleEngineResult,
    ToolErrorCode,
)
from creditpilot.tools.customer import CustomerEvidence
from creditpilot.tools.risk_model import RiskModelTool
from creditpilot.tools.rules import RuleEngineTool

_ISSUED_REPORTS: weakref.WeakValueDictionary[int, ValidationReport] = (
    weakref.WeakValueDictionary()
)


def _register_report(report: ValidationReport) -> ValidationReport:
    """Record the exact in-process report object issued by stage A."""

    _ISSUED_REPORTS[id(report)] = report
    return report


def is_stage_a_report_issued(report: ValidationReport) -> bool:
    """Reject copied or caller-constructed reports at the decision boundary."""

    return _ISSUED_REPORTS.get(id(report)) is report


def _canonical_digest(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _issue(
    code: ToolErrorCode,
    path: str,
    detail: str,
    *evidence_ids: str,
) -> ValidationIssue:
    return ValidationIssue(
        error_code=code,
        field_path=path,
        detail=detail,
        evidence_ids=tuple(evidence_ids),
    )


class EvidenceValidator:
    """Validate frozen Customer/Rule/Score outputs before policy evaluation."""

    def validate_stage_a(
        self,
        customer: CustomerRecord,
        customer_evidence: tuple[CustomerEvidence, ...],
        rule_result: RuleEngineResult,
        model_result: RiskModelResult,
    ) -> ValidationReport:
        issues: list[ValidationIssue] = []
        all_evidence = (
            *customer_evidence,
            *rule_result.evidence,
            *model_result.evidence,
        )

        if not rule_result.success or not model_result.success:
            issues.append(
                _issue(
                    ToolErrorCode.DEPENDENCY_NOT_VALIDATED,
                    "/dependencies",
                    "required rule and score tools must both succeed",
                )
            )

        for path, actual in (
            ("/rules/customer_id", rule_result.customer_id),
            ("/model/customer_id", model_result.customer_id),
        ):
            if actual != customer.customer_id:
                issues.append(
                    _issue(
                        ToolErrorCode.EVIDENCE_CONFLICT, path, "customer_id mismatch"
                    )
                )
        for path, actual in (
            ("/rules/data_version", rule_result.data_version),
            ("/model/data_version", model_result.data_version),
        ):
            if actual != customer.data_version:
                issues.append(
                    _issue(ToolErrorCode.EVIDENCE_STALE, path, "data_version mismatch")
                )
        if rule_result.rule_version != DEMO_RULE_VERSION:
            issues.append(
                _issue(
                    ToolErrorCode.EVIDENCE_STALE,
                    "/rules/rule_version",
                    "unsupported rule version",
                )
            )
        if model_result.model_version != DEMO_MODEL_VERSION:
            issues.append(
                _issue(
                    ToolErrorCode.EVIDENCE_STALE,
                    "/model/model_version",
                    "unsupported model version",
                )
            )

        self._validate_customer_evidence(customer, customer_evidence, issues)
        self._validate_rules(customer, rule_result, issues)
        self._validate_model(customer, model_result, issues)

        counts = Counter(item.evidence_id for item in all_evidence)
        duplicate_ids = sorted(item for item, count in counts.items() if count > 1)
        for evidence_id in duplicate_ids:
            issues.append(
                _issue(
                    ToolErrorCode.EVIDENCE_CONFLICT,
                    "/evidence",
                    "evidence_id must be globally unique",
                    evidence_id,
                )
            )

        status = (
            ValidationReportStatus.CONSISTENT
            if not issues
            else ValidationReportStatus.INCONSISTENT
        )
        references = tuple(
            EvidenceReference(
                evidence_id=item.evidence_id,
                source_tool=item.source_tool,
                validation_status=(
                    EvidenceStatus.VALID
                    if status is ValidationReportStatus.CONSISTENT
                    else EvidenceStatus.CONFLICT
                ),
            )
            for item in all_evidence
        )
        validated_ids = (
            tuple(reference.evidence_id for reference in references)
            if status is ValidationReportStatus.CONSISTENT
            else ()
        )
        report_seed = {
            "customer_id": customer.customer_id,
            "rule_digest": _canonical_digest(rule_result),
            "model_digest": _canonical_digest(model_result),
            "issues": [issue.model_dump(mode="json") for issue in issues],
        }
        report = ValidationReport(
            report_id=f"VR-A-{_canonical_digest(report_seed)[:16]}",
            customer_id=customer.customer_id,
            data_version=customer.data_version,
            rule_version=rule_result.rule_version,
            model_version=model_result.model_version,
            status=status,
            issues=tuple(issues),
            evidence_references=references,
            validated_evidence_ids=validated_ids,
            rule_result_digest=_canonical_digest(rule_result),
            model_result_digest=_canonical_digest(model_result),
            blocked_conclusions=("PASS", "REJECT") if issues else (),
        )
        return _register_report(report)

    def validate_stage_b(
        self,
        candidate: StructuredExplanation,
        stage_a_report: ValidationReport,
        decision: StructuredDecisionResult,
        rule_result: RuleEngineResult,
        model_result: RiskModelResult,
    ) -> StageBValidationReport:
        """Validate a whitelisted structured explanation without repairing it."""

        from creditpilot.tools.explanation import FixedTemplateEngine

        if not isinstance(decision, StructuredDecisionResult):
            raise TypeError("decision must use the frozen structured contract")

        issues: list[str] = []
        if (
            not is_stage_a_report_issued(stage_a_report)
            or stage_a_report.status is not ValidationReportStatus.CONSISTENT
        ):
            issues.append("DEPENDENCY_NOT_VALIDATED")
        expected = FixedTemplateEngine().render(decision, rule_result, model_result)
        if candidate != expected:
            issues.append("EXPLANATION_UNSUPPORTED")
        validated_ids = set(stage_a_report.validated_evidence_ids)
        if not set(candidate.evidence_ids) <= validated_ids:
            issues.append("EVIDENCE_SOURCE_INVALID")
        cited_ids = {
            evidence_id
            for item in (
                *candidate.policy_decision_reasons,
                *candidate.model_risk_factors,
            )
            for evidence_id in item.evidence_ids
        }
        if cited_ids != set(candidate.evidence_ids):
            issues.append("EVIDENCE_MISSING")
        issue_codes = tuple(dict.fromkeys(issues))
        seed = {
            "stage_a_report_id": stage_a_report.report_id,
            "candidate": candidate.model_dump(mode="json"),
            "issues": issue_codes,
        }
        return StageBValidationReport(
            report_id=f"VR-B-{_canonical_digest(seed)[:16]}",
            status="INCONSISTENT" if issue_codes else "CONSISTENT",
            issue_codes=issue_codes,
            blocked_output=("CANDIDATE_EXPLANATION" if issue_codes else "NONE"),
        )

    @staticmethod
    def _validate_customer_evidence(
        customer: CustomerRecord,
        evidence: tuple[CustomerEvidence, ...],
        issues: list[ValidationIssue],
    ) -> None:
        by_path = {item.field_path: item for item in evidence}
        snapshot = customer.model_dump(mode="json")
        for field_name, value in snapshot.items():
            path = f"/{field_name}"
            item = by_path.get(path)
            if item is None:
                issues.append(
                    _issue(
                        ToolErrorCode.EVIDENCE_MISSING,
                        path,
                        "customer evidence is missing",
                    )
                )
                continue
            if item.source_tool != "CustomerTool":
                issues.append(
                    _issue(
                        ToolErrorCode.EVIDENCE_SOURCE_INVALID,
                        path,
                        "invalid customer evidence source",
                        item.evidence_id,
                    )
                )
            if (item.customer_id, item.data_version, item.value) != (
                customer.customer_id,
                customer.data_version,
                value,
            ):
                issues.append(
                    _issue(
                        ToolErrorCode.EVIDENCE_CONFLICT,
                        path,
                        "customer evidence does not match snapshot",
                        item.evidence_id,
                    )
                )

    @staticmethod
    def _validate_rules(
        customer: CustomerRecord,
        result: RuleEngineResult,
        issues: list[ValidationIssue],
    ) -> None:
        expected = RuleEngineTool().evaluate(customer)
        ids = [execution.rule_id for execution in result.executions]
        if (
            len(ids) != 4
            or set(ids) != {"R001", "R002", "R003", "R004"}
            or len(ids) != len(set(ids))
        ):
            issues.append(
                _issue(
                    ToolErrorCode.EVIDENCE_MISSING,
                    "/rules/executions",
                    "R001-R004 must be complete and unique",
                )
            )
        if result.executions != expected.executions:
            issues.append(
                _issue(
                    ToolErrorCode.EVIDENCE_CONFLICT,
                    "/rules/executions",
                    "rule execution differs from frozen deterministic result",
                )
            )
        if (result.total_rule_count, result.matched_rule_count) != (
            expected.total_rule_count,
            expected.matched_rule_count,
        ):
            issues.append(
                _issue(
                    ToolErrorCode.EVIDENCE_CONFLICT,
                    "/rules/counts",
                    "rule counts are inconsistent",
                )
            )
        EvidenceValidator._validate_pending_evidence(
            result.evidence,
            expected.evidence,
            "RuleEngineTool",
            DEMO_RULE_VERSION,
            None,
            issues,
        )
        resolved = {item.evidence_id for item in result.evidence}
        for execution in result.executions:
            if (
                not execution.evidence_ids
                or not set(execution.evidence_ids) <= resolved
            ):
                issues.append(
                    _issue(
                        ToolErrorCode.EVIDENCE_MISSING,
                        f"/rules/{execution.rule_id}/evidence_ids",
                        "rule evidence reference cannot be resolved",
                    )
                )

    @staticmethod
    def _validate_model(
        customer: CustomerRecord,
        result: RiskModelResult,
        issues: list[ValidationIssue],
    ) -> None:
        expected = RiskModelTool().score(customer)
        factor_ids = [factor.factor_id for factor in result.factors]
        if len(factor_ids) != 6 or len(factor_ids) != len(set(factor_ids)):
            issues.append(
                _issue(
                    ToolErrorCode.EVIDENCE_MISSING,
                    "/model/factors",
                    "six score factors must be complete and unique",
                )
            )
        if result.factors != expected.factors:
            issues.append(
                _issue(
                    ToolErrorCode.EVIDENCE_CONFLICT,
                    "/model/factors",
                    "factor contributions differ from frozen formula",
                )
            )
        if result.score != sum(
            factor.rounded_contribution for factor in result.factors
        ):
            issues.append(
                _issue(
                    ToolErrorCode.EVIDENCE_CONFLICT,
                    "/model/score",
                    "score is not the sum of six contributions",
                )
            )
        if (result.score, result.risk_level) != (expected.score, expected.risk_level):
            issues.append(
                _issue(
                    ToolErrorCode.EVIDENCE_CONFLICT,
                    "/model/result",
                    "score or risk level differs from frozen result",
                )
            )
        EvidenceValidator._validate_pending_evidence(
            result.evidence,
            expected.evidence,
            "RiskModelTool",
            None,
            DEMO_MODEL_VERSION,
            issues,
        )
        resolved = {item.evidence_id for item in result.evidence}
        for factor in result.factors:
            if not factor.evidence_ids or not set(factor.evidence_ids) <= resolved:
                issues.append(
                    _issue(
                        ToolErrorCode.EVIDENCE_MISSING,
                        f"/model/{factor.factor_id}/evidence_ids",
                        "factor evidence reference cannot be resolved",
                    )
                )
        paths = {item.field_path for item in result.evidence}
        for path in ("/result/score", "/result/risk_level"):
            if path not in paths:
                issues.append(
                    _issue(
                        ToolErrorCode.EVIDENCE_MISSING,
                        path,
                        "model result evidence is missing",
                    )
                )

    @staticmethod
    def _validate_pending_evidence(
        actual: tuple[Any, ...],
        expected: tuple[Any, ...],
        source_tool: str,
        rule_version: str | None,
        model_version: str | None,
        issues: list[ValidationIssue],
    ) -> None:
        if actual != expected:
            issues.append(
                _issue(
                    ToolErrorCode.EVIDENCE_CONFLICT,
                    f"/{source_tool}/evidence",
                    "evidence content differs from deterministic source",
                )
            )
        for item in actual:
            if item.source_tool != source_tool:
                issues.append(
                    _issue(
                        ToolErrorCode.EVIDENCE_SOURCE_INVALID,
                        item.field_path,
                        "evidence source is invalid",
                        item.evidence_id,
                    )
                )
            if item.rule_version != rule_version or item.model_version != model_version:
                issues.append(
                    _issue(
                        ToolErrorCode.EVIDENCE_STALE,
                        item.field_path,
                        "evidence version is inconsistent",
                        item.evidence_id,
                    )
                )
            if item.validation_status != "PENDING":
                issues.append(
                    _issue(
                        ToolErrorCode.EVIDENCE_CONFLICT,
                        item.field_path,
                        "tool evidence must enter stage A as PENDING",
                        item.evidence_id,
                    )
                )


def result_digest(value: RuleEngineResult | RiskModelResult) -> str:
    """Expose the canonical digest used to bind a report to exact tool results."""

    return _canonical_digest(value)

"""Deterministic simulation policy over stage-A validated evidence."""

from creditpilot.models.decision import (
    STRATEGY_VERSION,
    AnalysisStatus,
    BusinessGuidanceContract,
    DecisionStatus,
    PolicyDecisionReason,
    StructuredDecisionResult,
    ValidationReport,
    ValidationReportStatus,
)
from creditpilot.models.risk import RiskModelResult, RuleEngineResult, ToolErrorCode
from creditpilot.tools.evidence import is_stage_a_report_issued, result_digest

RULE_REASON_IDS = {
    "R001": "P_R001_IDENTITY_UNVERIFIED",
    "R002": "P_R002_DELINQUENCY_THRESHOLD",
    "R003": "P_R003_DEBT_RATIO_THRESHOLD",
    "R004": "P_R004_REQUEST_RATIO_THRESHOLD",
}

RULE_GUIDANCE = {
    "R001": "BG_REVIEW_REQUIRED_DATA",
    "R002": "BG_REVIEW_RULE_EVIDENCE",
    "R003": "BG_REVIEW_RULE_EVIDENCE",
    "R004": "BG_REVIEW_RULE_EVIDENCE",
}


class DecisionTool:
    """Apply demo-policy-v1; never repairs or bypasses validation."""

    def decide(
        self,
        validation_report: ValidationReport,
        rule_result: RuleEngineResult,
        model_result: RiskModelResult,
        *,
        strategy_version: str = STRATEGY_VERSION,
    ) -> StructuredDecisionResult:
        dependency_valid = self._dependencies_valid(
            validation_report, rule_result, model_result
        )
        if not dependency_valid:
            return self._blocked(
                validation_report,
                rule_result,
                model_result,
                DecisionStatus.NEEDS_REVIEW,
                ToolErrorCode.DEPENDENCY_NOT_VALIDATED,
            )
        if strategy_version != STRATEGY_VERSION:
            return self._blocked(
                validation_report,
                rule_result,
                model_result,
                DecisionStatus.NOT_EVALUATED,
                ToolErrorCode.STRATEGY_VERSION_UNSUPPORTED,
            )

        reasons: list[PolicyDecisionReason] = []
        guidance: list[str] = []
        for execution in rule_result.executions:
            if execution.matched:
                reasons.append(
                    PolicyDecisionReason(
                        reason_id=RULE_REASON_IDS[execution.rule_id],
                        source_type="RULE",
                        source_id=execution.rule_id,
                        condition=(
                            f"{execution.rule_id}: {execution.operator} "
                            f"{execution.threshold}"
                        ),
                        evidence_ids=execution.evidence_ids,
                    )
                )
                guidance.append(RULE_GUIDANCE[execution.rule_id])

        if not reasons and model_result.score is not None and model_result.score < 500:
            score_evidence = tuple(
                item.evidence_id
                for item in model_result.evidence
                if item.field_path == "/result/score"
            )
            reasons.append(
                PolicyDecisionReason(
                    reason_id="P_SCORE_001",
                    source_type="SCORE_POLICY",
                    source_id="P_SCORE_001",
                    condition="score < 500",
                    evidence_ids=score_evidence,
                )
            )
            guidance.append("BG_REVIEW_SCORE_EVIDENCE")

        decision_status = DecisionStatus.REJECT if reasons else DecisionStatus.PASS
        if not guidance:
            guidance.append("BG_NO_REJECT_RULE")
        return StructuredDecisionResult(
            customer_id=validation_report.customer_id,
            data_version=validation_report.data_version,
            rule_version=validation_report.rule_version,
            model_version=validation_report.model_version,
            analysis_status=AnalysisStatus.SUCCESS,
            decision_status=decision_status,
            validation_report=validation_report,
            policy_reasons=tuple(reasons),
            model_risk_factors=model_result.factors,
            business_guidance=BusinessGuidanceContract(
                template_ids=tuple(dict.fromkeys(guidance))
            ),
            evidence_references=validation_report.evidence_references,
        )

    @staticmethod
    def _dependencies_valid(
        report: ValidationReport,
        rules: RuleEngineResult,
        model: RiskModelResult,
    ) -> bool:
        return (
            is_stage_a_report_issued(report)
            and report.status is ValidationReportStatus.CONSISTENT
            and rules.success
            and model.success
            and report.customer_id == rules.customer_id == model.customer_id
            and report.data_version == rules.data_version == model.data_version
            and report.rule_version == rules.rule_version
            and report.model_version == model.model_version
            and report.rule_result_digest == result_digest(rules)
            and report.model_result_digest == result_digest(model)
            and bool(report.validated_evidence_ids)
        )

    @staticmethod
    def _blocked(
        report: ValidationReport,
        rules: RuleEngineResult,
        model: RiskModelResult,
        decision_status: DecisionStatus,
        error_code: ToolErrorCode,
    ) -> StructuredDecisionResult:
        return StructuredDecisionResult(
            customer_id=report.customer_id,
            data_version=report.data_version,
            rule_version=report.rule_version,
            model_version=report.model_version,
            analysis_status=AnalysisStatus.PARTIAL,
            decision_status=decision_status,
            validation_report=report,
            policy_reasons=(),
            model_risk_factors=model.factors if model.success else (),
            business_guidance=BusinessGuidanceContract(
                template_ids=("BG_MANUAL_REVIEW_REQUIRED",)
            ),
            evidence_references=report.evidence_references,
            error_code=error_code,
        )

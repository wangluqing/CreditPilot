"""Fixed-order, offline orchestration for CreditPilot V0.1."""

from uuid import UUID, uuid4

from creditpilot.models.analysis import (
    AnalysisError,
    AnalysisVersions,
    AnalyzeRequest,
    AnalyzeResponse,
    RiskScore,
    RuleSummary,
    ScorePolicy,
    ValidationSummary,
)
from creditpilot.models.decision import (
    STRATEGY_VERSION,
    AnalysisStatus,
    DecisionStatus,
    ValidationReportStatus,
)
from creditpilot.models.explanation import StageBValidationReport
from creditpilot.tools.customer import CustomerTool
from creditpilot.tools.decision import DecisionTool
from creditpilot.tools.evidence import EvidenceValidator
from creditpilot.tools.explanation import FixedTemplateEngine
from creditpilot.tools.risk_model import RiskModelTool
from creditpilot.tools.rules import RuleEngineTool


class AnalysisOrchestrator:
    """Run the mandatory deterministic tools without user-selectable steps."""

    def __init__(
        self,
        customer_tool: CustomerTool,
        *,
        rule_tool: RuleEngineTool | None = None,
        model_tool: RiskModelTool | None = None,
        validator: EvidenceValidator | None = None,
        decision_tool: DecisionTool | None = None,
        template_engine: FixedTemplateEngine | None = None,
    ) -> None:
        self._customers = customer_tool
        self._rules = rule_tool or RuleEngineTool()
        self._model = model_tool or RiskModelTool()
        self._validator = validator or EvidenceValidator()
        self._decision = decision_tool or DecisionTool()
        self._templates = template_engine or FixedTemplateEngine()

    @classmethod
    def from_default_dataset(cls) -> "AnalysisOrchestrator":
        return cls(CustomerTool.from_default_dataset())

    def analyze(
        self,
        request: AnalyzeRequest,
        *,
        request_id: UUID | None = None,
    ) -> AnalyzeResponse:
        correlation_id = request_id or uuid4()
        if request.mode == "llm":
            return self._terminal_response(
                correlation_id,
                request.customer_id,
                AnalysisStatus.FAILED,
                "LLM_UNAVAILABLE",
                "llm mode is not enabled in this offline release",
            )

        try:
            customer_result = self._customers.lookup(request.customer_id)
        except Exception:
            return self._terminal_response(
                correlation_id,
                request.customer_id,
                AnalysisStatus.FAILED,
                "TOOL_UNAVAILABLE",
                "required local customer tool failed",
            )
        if customer_result.customer is None:
            status = AnalysisStatus(customer_result.analysis_status.value)
            first_error = customer_result.errors[0] if customer_result.errors else None
            return self._terminal_response(
                correlation_id,
                request.customer_id,
                status,
                first_error.code.value if first_error else "TOOL_UNAVAILABLE",
                first_error.message if first_error else "customer lookup failed",
                data_version=customer_result.data_version,
            )

        snapshot = customer_result.customer
        try:
            rules = self._rules.evaluate(snapshot)
            model = self._model.score(snapshot)
            report = self._validator.validate_stage_a(
                snapshot, customer_result.evidence, rules, model
            )
        except Exception:
            return self._terminal_response(
                correlation_id,
                snapshot.customer_id,
                AnalysisStatus.FAILED,
                "TOOL_UNAVAILABLE",
                "required deterministic tool chain failed",
                data_version=snapshot.data_version,
            )
        if report.status is not ValidationReportStatus.CONSISTENT:
            return AnalyzeResponse(
                request_id=correlation_id,
                analysis_status=AnalysisStatus.PARTIAL,
                decision_status=DecisionStatus.NEEDS_REVIEW,
                customer_id=snapshot.customer_id,
                data_version=snapshot.data_version,
                rule_version=rules.rule_version,
                model_version=model.model_version,
                versions=AnalysisVersions(
                    data_version=snapshot.data_version,
                    rule_version=rules.rule_version,
                    model_version=model.model_version,
                    strategy_version=STRATEGY_VERSION,
                ),
                evidence_references=report.evidence_references,
                explanation=self._templates.render_review(
                    snapshot.customer_id,
                    DecisionStatus.NEEDS_REVIEW,
                    "DEPENDENCY_NOT_VALIDATED",
                ),
                validation_reports=(
                    ValidationSummary(
                        report_id=report.report_id,
                        status=report.status.value,
                        issue_codes=tuple(
                            issue.error_code.value for issue in report.issues
                        ),
                    ),
                ),
                errors=(
                    AnalysisError(
                        code="DEPENDENCY_NOT_VALIDATED",
                        message="stage-A evidence validation failed",
                        source="EvidenceValidator",
                    ),
                ),
                error_code="DEPENDENCY_NOT_VALIDATED",
            )
        try:
            decision = self._decision.decide(report, rules, model)
        except Exception:
            return self._terminal_response(
                correlation_id,
                snapshot.customer_id,
                AnalysisStatus.FAILED,
                "TOOL_UNAVAILABLE",
                "required deterministic decision tool failed",
                data_version=snapshot.data_version,
            )
        try:
            candidate_explanation = self._templates.render(decision, rules, model)
            stage_b = self._validator.validate_stage_b(
                candidate_explanation, report, decision, rules, model
            )
        except Exception:
            candidate_explanation = None
            stage_b = StageBValidationReport(
                report_id="VR-B-RENDER-FAILED",
                status="INCONSISTENT",
                issue_codes=("EXPLANATION_UNSUPPORTED",),
                blocked_output="CANDIDATE_EXPLANATION",
            )
        explanation_valid = stage_b.status == "CONSISTENT"
        score_evidence = tuple(
            item.evidence_id
            for item in model.evidence
            if item.field_path == "/result/score"
        )
        risk_score = (
            RiskScore(
                score=model.score,
                level=model.risk_level,
                factors=model.factors,
            )
            if model.score is not None and model.risk_level is not None
            else None
        )
        score_policy = (
            ScorePolicy(
                condition_triggered=model.score < 500,
                pass_threshold_met=model.score >= 500,
                evidence_ids=score_evidence,
            )
            if model.score is not None
            else None
        )
        error_code = decision.error_code.value if decision.error_code else None
        if not explanation_valid:
            error_code = "EXPLANATION_UNSUPPORTED"
        errors = (
            (
                AnalysisError(
                    code=error_code,
                    message=(
                        "candidate explanation failed deterministic validation"
                        if error_code == "EXPLANATION_UNSUPPORTED"
                        else "required deterministic evidence was not validated"
                    ),
                    source=(
                        "EvidenceValidator"
                        if error_code == "EXPLANATION_UNSUPPORTED"
                        else "DecisionTool"
                    ),
                ),
            )
            if error_code
            else ()
        )
        summary = ValidationSummary(
            report_id=report.report_id,
            status=report.status.value,
            issue_codes=tuple(issue.error_code.value for issue in report.issues),
        )
        stage_b_summary = ValidationSummary(
            report_id=stage_b.report_id,
            stage="B",
            status=stage_b.status,
            issue_codes=stage_b.issue_codes,
        )
        versions = AnalysisVersions(
            data_version=snapshot.data_version,
            rule_version=rules.rule_version,
            model_version=model.model_version,
            strategy_version=STRATEGY_VERSION,
        )
        return AnalyzeResponse(
            request_id=correlation_id,
            analysis_status=(
                decision.analysis_status
                if explanation_valid
                else AnalysisStatus.PARTIAL
            ),
            decision_status=decision.decision_status,
            customer_id=snapshot.customer_id,
            data_version=snapshot.data_version,
            rule_version=rules.rule_version,
            model_version=model.model_version,
            versions=versions,
            score=model.score,
            risk_level=model.risk_level,
            rule_results=rules.executions,
            rule_summary=RuleSummary(
                total=rules.total_rule_count,
                matched=rules.matched_rule_count,
                executions=rules.executions,
            ),
            risk_score=risk_score,
            score_policy=score_policy,
            policy_reasons=decision.policy_reasons,
            policy_decision_reasons=decision.policy_reasons,
            model_risk_factors=decision.model_risk_factors,
            business_guidance=decision.business_guidance,
            explanation=candidate_explanation if explanation_valid else None,
            evidence_references=decision.evidence_references,
            validation_reports=(summary, stage_b_summary),
            errors=errors,
            error_code=error_code,
        )

    @staticmethod
    def _terminal_response(
        request_id: UUID,
        customer_id: str | None,
        analysis_status: AnalysisStatus,
        error_code: str,
        message: str,
        *,
        data_version: str | None = None,
    ) -> AnalyzeResponse:
        return AnalyzeResponse(
            request_id=request_id,
            analysis_status=analysis_status,
            decision_status=DecisionStatus.NOT_EVALUATED,
            customer_id=customer_id,
            data_version=data_version,
            versions=AnalysisVersions(data_version=data_version),
            explanation=FixedTemplateEngine().render_review(
                customer_id,
                DecisionStatus.NOT_EVALUATED,
                error_code,
            ),
            errors=(
                AnalysisError(
                    code=error_code,
                    message=message,
                    source="AnalysisOrchestrator",
                ),
            ),
            error_code=error_code,
        )

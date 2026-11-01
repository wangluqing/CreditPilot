"""Deterministic Chinese rendering from validated structured facts."""

from creditpilot.models.decision import DecisionStatus, StructuredDecisionResult
from creditpilot.models.explanation import (
    BusinessGuidanceExplanation,
    ModelFactorExplanation,
    PolicyReasonExplanation,
    ReviewExplanation,
    StructuredExplanation,
)
from creditpilot.models.risk import RiskModelResult, RuleEngineResult

LIMITATION = "仅用于原创合成数据演示，不构成真实授信审批、额度调整或风险预测。"


class FixedTemplateEngine:
    """Render only whitelisted templates; no LLM or free-form generation."""

    def render(
        self,
        decision: StructuredDecisionResult,
        rules: RuleEngineResult,
        model: RiskModelResult,
    ) -> StructuredExplanation:
        if model.score is None or model.risk_level is None:
            raise ValueError("a complete validated score is required")

        executions = {item.rule_id: item for item in rules.executions}
        policy_items: list[PolicyReasonExplanation] = []
        for reason in decision.policy_reasons:
            if reason.source_type == "RULE":
                execution = executions[reason.source_id]
                actual_value = execution.actual_value
                text = (
                    f"模拟规则 {execution.rule_id} 已命中：实际值 "
                    f"{actual_value}，条件为 {execution.operator} "
                    f"{execution.threshold}。"
                )
            else:
                actual_value = model.score
                text = (
                    f"演示评分门槛 P_SCORE_001 已触发：当前分数 "
                    f"{model.score}，条件为 score < 500。"
                )
            policy_items.append(
                PolicyReasonExplanation(
                    reason_id=reason.reason_id,
                    source_type=reason.source_type,
                    source_id=reason.source_id,
                    condition=reason.condition,
                    actual_value=actual_value,
                    text=text,
                    evidence_ids=reason.evidence_ids,
                )
            )

        factor_items = tuple(
            ModelFactorExplanation(
                factor_id=factor.factor_id,
                contribution=factor.rounded_contribution,
                max_contribution=factor.max_contribution,
                text=(
                    f"{factor.factor_id} 贡献 {factor.rounded_contribution}/"
                    f"{factor.max_contribution}；该模型因素不自动等同于拒绝原因。"
                ),
                evidence_ids=factor.evidence_ids,
            )
            for factor in model.factors
        )
        matched_ids = tuple(item.rule_id for item in rules.executions if item.matched)
        has_score_reason = any(
            item.reason_id == "P_SCORE_001" for item in decision.policy_reasons
        )
        if decision.decision_status is DecisionStatus.PASS:
            summary = (
                f"未触发模拟拒绝规则；演示评分为 {model.score}，"
                "已满足 500 分门槛。"
            )
            guidance = BusinessGuidanceExplanation(
                template_id="BG_NO_REJECT_RULE",
                text="请核对合成资料和版本记录；该结果不表示真实授信批准。",
                review_actions=("核对合成客户资料完整性", "核对规则、模型和策略版本"),
                limitation=LIMITATION,
            )
        elif matched_ids and has_score_reason:
            summary = (
                f"命中 {len(matched_ids)} 条模拟拒绝规则，且演示评分 "
                f"{model.score} 未满足 500 分门槛。"
            )
            guidance = BusinessGuidanceExplanation(
                template_id="BG_REVIEW_RULE_AND_SCORE_EVIDENCE",
                text="请分别复核规则证据和评分证据，不得将模型因素替代策略原因。",
                review_actions=("复核命中规则的实际值", "复核六项评分贡献与总分"),
                limitation=LIMITATION,
            )
        elif matched_ids:
            summary = f"命中 {len(matched_ids)} 条模拟拒绝规则。"
            guidance = BusinessGuidanceExplanation(
                template_id="BG_REVIEW_RULE_EVIDENCE",
                text="请逐条复核命中规则的合成字段、阈值和证据引用。",
                review_actions=("复核命中规则实际值", "确认规则版本与数据版本一致"),
                limitation=LIMITATION,
            )
        else:
            summary = (
                f"未命中模拟拒绝规则，但演示评分 {model.score} "
                "未满足 500 分门槛。"
            )
            guidance = BusinessGuidanceExplanation(
                template_id="BG_REVIEW_SCORE_EVIDENCE",
                text="请复核六项评分贡献和总分；评分因素不等同于规则拒绝原因。",
                review_actions=("复核六项贡献求和", "核对评分门槛证据"),
                limitation=LIMITATION,
            )

        evidence_ids = tuple(
            dict.fromkeys(
                evidence_id
                for item in (*policy_items, *factor_items)
                for evidence_id in item.evidence_ids
            )
        )
        return StructuredExplanation(
            customer_id=decision.customer_id,
            data_version=decision.data_version,
            rule_version=decision.rule_version,
            model_version=decision.model_version,
            decision_status=decision.decision_status,
            summary=summary,
            score=model.score,
            risk_level=model.risk_level,
            score_threshold_met=model.score >= 500,
            matched_rule_ids=matched_ids,
            rule_total=rules.total_rule_count,
            policy_decision_reasons=tuple(policy_items),
            model_risk_factors=factor_items,
            business_guidance=guidance,
            evidence_ids=evidence_ids,
        )

    def render_review(
        self,
        customer_id: str | None,
        decision_status: DecisionStatus,
        error_code: str,
    ) -> ReviewExplanation:
        summaries = {
            "CUSTOMER_NOT_FOUND": "未找到对应的合成客户，未执行模拟分析。",
            "INVALID_CUSTOMER_ID": "输入未通过校验，未执行模拟分析。",
            "INVALID_QUESTION": "输入未通过校验，未执行模拟分析。",
            "INVALID_MODE": "输入未通过校验，未执行模拟分析。",
            "DEPENDENCY_NOT_VALIDATED": "必需证据未通过校验，无法形成确定性模拟结论。",
        }
        return ReviewExplanation(
            customer_id=customer_id,
            decision_status=decision_status,
            summary=summaries.get(
                error_code, "分析未完成，未形成确定性模拟结论。"
            ),
            business_guidance=BusinessGuidanceExplanation(
                template_id="BG_MANUAL_REVIEW_REQUIRED",
                text="请核对输入、合成资料及工具状态后再试，不得据此执行真实业务操作。",
                review_actions=("核对请求与合成客户编号", "核对必需工具和证据状态"),
                limitation=LIMITATION,
            ),
        )

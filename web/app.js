"use strict";

const byId = (id) => document.getElementById(id);
let latestReport = null;

function clearNode(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

function addDefinition(list, key, value) {
  list.append(element("dt", key));
  list.append(element("dd", value ?? "—"));
}

function stageBIsValid(data) {
  return (data.validation_reports || []).some(
    (report) => report.stage === "B" && report.status === "CONSISTENT"
  );
}

function setStatus(node, value) {
  node.textContent = value || "—";
  node.className = value === "PASS" || value === "SUCCESS"
    ? "status-pass"
    : value === "REJECT" || value === "FAILED"
      ? "status-reject"
      : "status-warning";
}

function renderPolicyReasons(data) {
  const target = byId("policy-reasons");
  clearNode(target);
  const reasons = data.policy_reasons || [];
  if (!reasons.length) {
    target.append(element("p", "无模拟策略拒绝原因。", "section-note"));
    return;
  }
  reasons.forEach((reason) => {
    const card = element("article", null, "item-card");
    card.append(element("strong", `${reason.reason_id} · ${reason.source_type}`));
    card.append(element("div", reason.condition));
    card.append(element("small", (reason.evidence_ids || []).join(" · ")));
    target.append(card);
  });
}

function renderModelFactors(data) {
  const target = byId("model-factors");
  clearNode(target);
  (data.model_risk_factors || []).forEach((factor) => {
    const card = element("article", null, "item-card");
    card.append(element("strong", factor.factor_id));
    card.append(element("div", `${factor.rounded_contribution} / ${factor.max_contribution}`));
    const bar = document.createElement("progress");
    bar.className = "factor-bar";
    bar.max = factor.max_contribution || 1;
    bar.value = Math.max(0, factor.rounded_contribution || 0);
    bar.setAttribute("aria-label", `${factor.factor_id} 贡献`);
    card.append(bar);
    card.append(element("small", "模型贡献，不自动等同于拒绝原因"));
    target.append(card);
  });
}

function renderRules(data) {
  const target = byId("rule-records");
  clearNode(target);
  (data.rule_results || []).forEach((rule) => {
    const row = document.createElement("tr");
    row.append(element("td", rule.rule_id));
    row.append(element("td", rule.actual_value));
    row.append(element("td", `${rule.operator} ${rule.threshold}`));
    row.append(element("td", rule.matched ? "命中" : "未命中", rule.matched ? "matched" : "not-matched"));
    target.append(row);
  });
}

function renderVersionsAndValidation(data) {
  const versions = byId("versions");
  clearNode(versions);
  addDefinition(versions, "数据版本", data.versions?.data_version);
  addDefinition(versions, "规则版本", data.versions?.rule_version);
  addDefinition(versions, "评分版本", data.versions?.model_version);
  addDefinition(versions, "策略版本", data.versions?.strategy_version);
  addDefinition(versions, "响应契约", data.versions?.contract_version);

  const reports = byId("validation-reports");
  clearNode(reports);
  (data.validation_reports || []).forEach((report) => {
    const card = element("div", null, "item-card");
    card.append(element("strong", `阶段 ${report.stage} · ${report.status}`));
    card.append(element("small", report.report_id));
    if ((report.issue_codes || []).length) {
      card.append(element("div", report.issue_codes.join(" · ")));
    }
    reports.append(card);
  });
}

function renderEvidence(data) {
  const target = byId("evidence-list");
  clearNode(target);
  (data.evidence_references || []).forEach((reference) => {
    target.append(element(
      "div",
      `${reference.evidence_id} · ${reference.source_tool} · ${reference.validation_status}`,
      "evidence-chip"
    ));
  });
  if (!target.childElementCount) target.append(element("p", "无可展示证据。", "section-note"));
}

function renderExplanation(data) {
  const section = byId("explanation-section");
  const notice = byId("result-notice");
  notice.hidden = true;
  notice.textContent = "";
  const verified = stageBIsValid(data) && data.explanation;
  section.hidden = !verified;
  if (verified) {
    byId("explanation-summary").textContent = data.explanation.summary;
    const guidance = byId("guidance");
    clearNode(guidance);
    guidance.append(element("strong", "Business Guidance"));
    guidance.append(element("p", data.explanation.business_guidance.text));
    (data.explanation.business_guidance.review_actions || []).forEach((action) => {
      guidance.append(element("div", `• ${action}`));
    });
    guidance.append(element("small", data.explanation.business_guidance.limitation));
    return;
  }
  if (data.analysis_status === "PARTIAL") {
    notice.textContent = "确定性模拟决策已保留，但阶段 B 未通过，未经验证的候选解释不会展示，请人工复核。";
  } else {
    const error = (data.errors || [])[0];
    notice.textContent = error?.message || data.explanation?.summary || "当前请求未形成可展示的确定性分析。";
  }
  notice.hidden = false;
}

function renderResult(data) {
  latestReport = data;
  byId("result").hidden = false;
  setStatus(byId("analysis-status"), data.analysis_status);
  setStatus(byId("decision-status"), data.decision_status);
  byId("result-customer").textContent = data.customer_id || "—";
  byId("score").textContent = data.score ?? "—";
  byId("risk-level").textContent = data.risk_level ?? "—";
  byId("score-threshold").textContent = data.score_policy
    ? (data.score_policy.pass_threshold_met ? "已满足" : "未满足")
    : "—";
  byId("rule-count").textContent = data.rule_summary
    ? `${data.rule_summary.matched} / ${data.rule_summary.total}`
    : "—";
  renderExplanation(data);
  renderPolicyReasons(data);
  renderModelFactors(data);
  renderRules(data);
  renderVersionsAndValidation(data);
  renderEvidence(data);
  byId("raw-json").textContent = JSON.stringify(data, null, 2);
  byId("disclaimer").textContent = data.disclaimer || "仅限合成演示，不构成真实授信建议。";
  byId("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

function setLoading(active) {
  byId("submit-button").disabled = active;
  document.querySelector(".button-label").hidden = active;
  document.querySelector(".button-loading").hidden = !active;
}

async function submitAnalysis(event) {
  event.preventDefault();
  const message = byId("form-message");
  message.textContent = "";
  setLoading(true);
  try {
    const response = await fetch("/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_id: byId("customer-id").value.trim(),
        question: byId("question").value.trim(),
        mode: byId("mode").value
      })
    });
    const data = await response.json();
    renderResult(data);
    if (!response.ok) message.textContent = `请求未完成：${data.error_code || response.status}`;
  } catch (_error) {
    message.textContent = "无法连接本地 CreditPilot 服务，请确认服务已启动。";
  } finally {
    setLoading(false);
  }
}

async function copyReport() {
  if (!latestReport) return;
  await navigator.clipboard.writeText(JSON.stringify(latestReport, null, 2));
  byId("form-message").textContent = "结构化报告已复制。";
}

function downloadReport() {
  if (!latestReport) return;
  const blob = new Blob([JSON.stringify(latestReport, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `creditpilot-${latestReport.customer_id || "report"}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

byId("analysis-form").addEventListener("submit", submitAnalysis);
byId("copy-report").addEventListener("click", copyReport);
byId("download-report").addEventListener("click", downloadReport);

window.CreditPilotUI = Object.freeze({ renderResult, stageBIsValid });

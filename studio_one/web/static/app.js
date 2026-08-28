const STAGES = [
  { id: "brainstorm", label: "BRAINSTORM" },
  { id: "refine", label: "REFINE" },
  { id: "finalize_storyboard", label: "FINALIZE STORYBOARD" },
  { id: "generate_assets", label: "GENERATE ASSETS" },
  { id: "quality_control", label: "QUALITY CONTROL" },
  { id: "post_production", label: "POST PRODUCTION" },
  { id: "publish", label: "PUBLISH" },
];

const state = {
  activeStage: STAGES[0].id,
  projectId: "",
  projectTitle: "",
  workflow: null,
  memory: null,
  latest: {},
};

const dom = {
  projectForm: document.querySelector("#project-form"),
  projectTitle: document.querySelector("#project-title"),
  projectIntent: document.querySelector("#project-intent"),
  projectConstraints: document.querySelector("#project-constraints"),
  activeProjectTitle: document.querySelector("#active-project-title"),
  stageNav: document.querySelector("#stage-nav"),
  stageKicker: document.querySelector("#stage-kicker"),
  stageTitle: document.querySelector("#stage-title"),
  actionContent: document.querySelector("#action-content"),
  outputContent: document.querySelector("#output-content"),
  memoryContent: document.querySelector("#memory-content"),
  doesList: document.querySelector("#does-list"),
  doesNotList: document.querySelector("#does-not-list"),
  toast: document.querySelector("#toast"),
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  renderStageNav();
  renderActionPanel();
  dom.projectForm.addEventListener("submit", handleCreateProject);
  document.addEventListener("click", handleDocumentClick);
  try {
    state.workflow = await api("/api/workflow");
    renderBoundaries();
  } catch (error) {
    showToast(error.message);
  }
}

function renderStageNav() {
  dom.stageNav.innerHTML = "";
  STAGES.forEach((stage, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `stage-button ${stage.id === state.activeStage ? "active" : ""}`;
    button.dataset.stage = stage.id;
    button.innerHTML = `
      <span class="stage-index">${index + 1}</span>
      <span>${escapeHtml(stage.label)}</span>
    `;
    dom.stageNav.append(button);
  });
}

function handleDocumentClick(event) {
  const stageButton = event.target.closest("[data-stage]");
  if (stageButton) {
    state.activeStage = stageButton.dataset.stage;
    renderStageNav();
    renderActionPanel();
    return;
  }

  const actionButton = event.target.closest("[data-action]");
  if (actionButton) {
    runAction(actionButton.dataset.action);
    return;
  }

  const copyButton = event.target.closest("[data-copy]");
  if (copyButton) {
    copyText(copyButton.dataset.copy || "");
  }
}

async function handleCreateProject(event) {
  event.preventDefault();
  const payload = {
    title: dom.projectTitle.value.trim(),
    initial_creative_intent: dom.projectIntent.value.trim(),
    production_constraints: dom.projectConstraints.value.trim(),
  };
  if (!payload.title || !payload.initial_creative_intent) {
    showToast("Project title and creative intent are required.");
    return;
  }

  await runWithOutput("Creating project and entering BRAINSTORM", async () => {
    const result = await api("/api/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.projectId = result.project?.project_id || "";
    state.projectTitle = result.project?.title || payload.title;
    state.activeStage = "brainstorm";
    state.latest.brainstorm = result;
    renderProjectHeader();
    renderStageNav();
    renderActionPanel();
    renderOutput(result);
    await refreshMemory();
  });
}

function renderProjectHeader() {
  dom.activeProjectTitle.textContent = state.projectTitle || "No project selected";
}

function renderActionPanel() {
  const stage = STAGES.find((item) => item.id === state.activeStage) || STAGES[0];
  dom.stageKicker.textContent = stage.label;
  dom.stageTitle.textContent = actionTitle(stage.id);
  dom.actionContent.innerHTML = actionMarkup(stage.id);
  hydrateDynamicValues();
}

function actionTitle(stageId) {
  return {
    brainstorm: "Expand the production premise",
    refine: "Direct the next creative pass",
    finalize_storyboard: "Request and approve storyboard candidates",
    generate_assets: "Prepare creator-facing asset packages",
    quality_control: "Intake external assets and route QC",
    post_production: "Prepare the manual editing package",
    publish: "Prepare the manual publishing package",
  }[stageId];
}

function actionMarkup(stageId) {
  if (!state.projectId) {
    return `<div class="empty-state">Create a project before running canonical stages.</div>`;
  }

  const forms = {
    brainstorm: `
      <div class="stack">
        <p class="empty-state">BRAINSTORM retrieves production memory and returns structured creative options for creator direction.</p>
        <button type="button" data-action="brainstorm">Run BRAINSTORM</button>
      </div>
    `,
    refine: `
      <div class="stack">
        <label>Creator Direction
          <textarea id="refine-direction" rows="5" required></textarea>
        </label>
        <button type="button" data-action="refine">Run REFINE</button>
      </div>
    `,
    finalize_storyboard: `
      <div class="stack">
        <label>Creator Action
          <textarea id="storyboard-action" rows="5" required></textarea>
        </label>
        <label>Target Runtime
          <input id="storyboard-runtime" autocomplete="off" />
        </label>
        <div class="button-row">
          <button type="button" data-action="storyboard">Create Storyboard Candidate</button>
          <button type="button" class="secondary" data-action="submit-storyboard-review">Submit Candidate for Review</button>
        </div>
        <div class="form-grid">
          <label>Storyboard Review ID
            <input id="storyboard-review-id" autocomplete="off" />
          </label>
          <label>Reviewer
            <input id="storyboard-reviewer" autocomplete="off" />
          </label>
          <label class="full">Decision Reason
            <textarea id="storyboard-decision-reason" rows="3"></textarea>
          </label>
        </div>
        <div class="button-row">
          <button type="button" data-action="approve-storyboard">Approve</button>
          <button type="button" class="warn" data-action="revise-storyboard">Needs Revision</button>
          <button type="button" class="danger" data-action="reject-storyboard">Reject</button>
        </div>
      </div>
    `,
    generate_assets: `
      <div class="stack">
        <p class="empty-state">This creates prompt packages and handoff instructions. STUDIO//ONE does not generate media assets itself.</p>
        <button type="button" data-action="generate-assets">Prepare Asset Package</button>
      </div>
    `,
    quality_control: `
      <div class="stack">
        <div class="form-grid">
          <label>Approved Storyboard ID
            <input id="qc-storyboard-id" autocomplete="off" />
          </label>
          <label>Approved Storyboard Version
            <input id="qc-storyboard-version" type="number" min="1" value="1" />
          </label>
          <label>Panel or Shot Reference
            <input id="qc-shot-ref" autocomplete="off" />
          </label>
          <label>Asset Type
            <input id="qc-asset-type" autocomplete="off" />
          </label>
          <label class="full">External Asset Reference
            <input id="qc-external-ref" autocomplete="off" />
          </label>
          <label>Submitted By
            <input id="qc-submitted-by" autocomplete="off" />
          </label>
          <label>Generation Package ID
            <input id="qc-package-id" autocomplete="off" />
          </label>
          <label>Generation Package Version
            <input id="qc-package-version" type="number" min="0" value="0" />
          </label>
          <label class="full">Creator Metadata JSON
            <textarea id="qc-metadata" rows="3">{}</textarea>
          </label>
        </div>
        <button type="button" data-action="external-asset">Submit External Asset Candidate</button>
        <div class="form-grid">
          <label>External Asset Candidate ID
            <input id="qc-candidate-id" autocomplete="off" />
          </label>
          <label>QC Review ID
            <input id="qc-review-id" autocomplete="off" />
          </label>
          <label>QC Reviewer
            <input id="qc-reviewer" autocomplete="off" />
          </label>
          <label class="full">QC Decision Reason
            <textarea id="qc-decision-reason" rows="3"></textarea>
          </label>
        </div>
        <div class="button-row">
          <button type="button" data-action="quality-control">Run Gemini QC</button>
          <button type="button" data-action="approve-qc">Approve Asset</button>
          <button type="button" class="warn" data-action="revise-qc">Needs Revision</button>
          <button type="button" class="danger" data-action="reject-qc">Reject Asset</button>
        </div>
      </div>
    `,
    post_production: `
      <div class="stack">
        <p class="empty-state">POST PRODUCTION prepares manual editing instructions. It does not edit or claim final media completion.</p>
        <button type="button" data-action="post-production">Prepare Editing Package</button>
      </div>
    `,
    publish: `
      <div class="stack">
        <div class="form-grid">
          <label class="full">Final Edit Reference
            <input id="publish-final-ref" autocomplete="off" />
          </label>
          <label>Final Edit Complete
            <select id="publish-final-complete">
              <option value="false">No explicit completion supplied</option>
              <option value="true">Creator confirms final edit complete</option>
            </select>
          </label>
          <label>Requested Platform Orientations
            <input id="publish-platforms" autocomplete="off" placeholder="short-form social, long-form video" />
          </label>
          <label class="full">Final Edit Notes
            <textarea id="publish-notes" rows="3"></textarea>
          </label>
          <label class="full">Required Metadata JSON
            <textarea id="publish-metadata" rows="3">{}</textarea>
          </label>
        </div>
        <p class="empty-state">PUBLISH prepares options for creator approval and manual posting. It never uploads, schedules, posts, or authenticates to platforms.</p>
        <button type="button" data-action="publish">Prepare Publish Package</button>
      </div>
    `,
  };
  return forms[stageId] || "";
}

function hydrateDynamicValues() {
  setValue("#storyboard-review-id", state.latest.storyboardReview?.review_id);
  setValue("#qc-storyboard-id", state.memory?.approved_storyboard?.storyboard_id);
  setValue("#qc-storyboard-version", state.memory?.approved_storyboard?.version || "");
  setValue("#qc-candidate-id", state.latest.externalAsset?.candidate?.external_asset_candidate_id);
  setValue("#qc-review-id", state.latest.qualityControl?.review?.review_id);
}

async function runAction(action) {
  const actions = {
    brainstorm: runBrainstorm,
    refine: runRefine,
    storyboard: runStoryboard,
    "submit-storyboard-review": submitStoryboardReview,
    "approve-storyboard": () => decideStoryboard("approve"),
    "revise-storyboard": () => decideStoryboard("needs_revision"),
    "reject-storyboard": () => decideStoryboard("reject"),
    "generate-assets": runGenerateAssets,
    "external-asset": submitExternalAsset,
    "quality-control": runQualityControl,
    "approve-qc": () => decideQualityControl("approve"),
    "revise-qc": () => decideQualityControl("needs_revision"),
    "reject-qc": () => decideQualityControl("reject"),
    "post-production": runPostProduction,
    publish: runPublish,
  };
  const handler = actions[action];
  if (!handler) return;
  await runWithOutput("Running stage", handler);
}

async function runBrainstorm() {
  const result = await api(`/api/projects/${encodeURIComponent(state.projectId)}/brainstorm`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  state.latest.brainstorm = result;
  renderOutput(result);
  await refreshMemory();
}

async function runRefine() {
  const creatorDirection = valueOf("#refine-direction");
  const result = await api(`/api/projects/${encodeURIComponent(state.projectId)}/refine`, {
    method: "POST",
    body: JSON.stringify({ creator_direction: creatorDirection }),
  });
  state.latest.refine = result;
  renderOutput(result);
  await refreshMemory();
}

async function runStoryboard() {
  const result = await api(`/api/projects/${encodeURIComponent(state.projectId)}/storyboard`, {
    method: "POST",
    body: JSON.stringify({
      creator_action: valueOf("#storyboard-action"),
      target_total_runtime: valueOf("#storyboard-runtime"),
    }),
  });
  state.latest.storyboard = result;
  renderOutput(result);
  await refreshMemory();
}

async function submitStoryboardReview() {
  const candidate = state.latest.storyboard?.storyboard_candidate;
  if (!candidate) throw new Error("Create a storyboard candidate before submitting review.");
  const result = await api("/api/storyboard/reviews", {
    method: "POST",
    body: JSON.stringify({
      project_id: state.projectId,
      storyboard_candidate: candidate,
      source_reference: "studio_one_web",
      evidence_references: ["ui:storyboard-candidate"],
      gemini_prompt_version: "finalize_storyboard:v1",
      confidence: Number(candidate.confidence || 0),
    }),
  });
  state.latest.storyboardReview = result;
  renderOutput(result);
  renderActionPanel();
  await refreshMemory();
}

async function decideStoryboard(action) {
  const result = await api("/api/storyboard/decisions", {
    method: "POST",
    body: JSON.stringify({
      project_id: state.projectId,
      review_id: valueOf("#storyboard-review-id"),
      action,
      decided_by: valueOf("#storyboard-reviewer"),
      decision_reason: valueOf("#storyboard-decision-reason"),
      reviewer_identity_source: "studio_one_web_creator_input",
    }),
  });
  state.latest.storyboardDecision = result;
  renderOutput(result);
  await refreshMemory();
}

async function runGenerateAssets() {
  const result = await api(`/api/projects/${encodeURIComponent(state.projectId)}/generate-assets`, {
    method: "POST",
  });
  state.latest.generateAssets = result;
  renderOutput(result);
  await refreshMemory();
}

async function submitExternalAsset() {
  const metadata = parseJsonField("#qc-metadata", {});
  const result = await api("/api/external-assets", {
    method: "POST",
    body: JSON.stringify({
      project_id: state.projectId,
      approved_storyboard_id: valueOf("#qc-storyboard-id"),
      approved_storyboard_version: Number(valueOf("#qc-storyboard-version") || 1),
      storyboard_panel_shot_reference: valueOf("#qc-shot-ref"),
      asset_type: valueOf("#qc-asset-type"),
      external_asset_reference: valueOf("#qc-external-ref"),
      submitted_by: valueOf("#qc-submitted-by"),
      source_generation_package_id: valueOf("#qc-package-id") || null,
      source_generation_package_version: Number(valueOf("#qc-package-version") || 0),
      creator_supplied_metadata: metadata,
      source_reference: "studio_one_web_external_asset_intake",
      evidence_references: ["ui:external-asset-reference"],
    }),
  });
  state.latest.externalAsset = result;
  renderOutput(result);
  renderActionPanel();
  await refreshMemory();
}

async function runQualityControl() {
  const result = await api(`/api/projects/${encodeURIComponent(state.projectId)}/quality-control`, {
    method: "POST",
    body: JSON.stringify({
      external_asset_candidate_id: valueOf("#qc-candidate-id"),
    }),
  });
  state.latest.qualityControl = result;
  renderOutput(result);
  renderActionPanel();
  await refreshMemory();
}

async function decideQualityControl(action) {
  const result = await api("/api/quality-control/decisions", {
    method: "POST",
    body: JSON.stringify({
      project_id: state.projectId,
      review_id: valueOf("#qc-review-id"),
      action,
      decided_by: valueOf("#qc-reviewer"),
      decision_reason: valueOf("#qc-decision-reason"),
      reviewer_identity_source: "studio_one_web_creator_input",
    }),
  });
  state.latest.qcDecision = result;
  renderOutput(result);
  await refreshMemory();
}

async function runPostProduction() {
  const result = await api(`/api/projects/${encodeURIComponent(state.projectId)}/post-production`, {
    method: "POST",
  });
  state.latest.postProduction = result;
  renderOutput(result);
  await refreshMemory();
}

async function runPublish() {
  const platforms = valueOf("#publish-platforms")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const result = await api(`/api/projects/${encodeURIComponent(state.projectId)}/publish`, {
    method: "POST",
    body: JSON.stringify({
      final_edit_reference: valueOf("#publish-final-ref") || null,
      final_edit_is_complete: valueOf("#publish-final-complete") === "true",
      final_edit_notes: valueOf("#publish-notes"),
      required_metadata: parseJsonField("#publish-metadata", {}),
      requested_platforms: platforms,
      post_production_package: state.latest.postProduction?.package || null,
    }),
  });
  state.latest.publish = result;
  renderOutput(result);
  await refreshMemory();
}

async function refreshMemory() {
  if (!state.projectId) return;
  try {
    state.memory = await api(`/api/projects/${encodeURIComponent(state.projectId)}/memory`);
    renderMemory();
  } catch (error) {
    dom.memoryContent.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

function renderMemory() {
  if (!state.memory) return;
  const memory = state.memory;
  dom.memoryContent.innerHTML = `
    <div class="result-stack">
      ${definitionList("Project", memory.project || {})}
      ${definitionList("Approved Storyboard", memory.approved_storyboard || {})}
      ${listCard("Pending Reviews", memory.pending_reviews || [])}
      ${listCard("Human Decisions", memory.human_decisions || [])}
      ${listCard("Provenance References", memory.provenance_references || [])}
      ${definitionList("Retrieval", memory.retrieval || {})}
    </div>
  `;
}

function renderBoundaries() {
  renderList(dom.doesList, state.workflow?.does || []);
  renderList(dom.doesNotList, state.workflow?.does_not || []);
}

function renderOutput(result) {
  dom.outputContent.className = "result-stack";
  dom.outputContent.innerHTML = resultMarkup(result);
}

function resultMarkup(value) {
  if (!value || typeof value !== "object") {
    return `<pre>${escapeHtml(String(value ?? ""))}</pre>`;
  }
  const stage = value.stage ? `<span class="pill">${escapeHtml(value.stage)}</span>` : "";
  const copySections = [
    optionSection("Title Options", value.package?.title_options),
    optionSection("SEO Keyword Options", value.package?.seo_keyword_options),
    optionSection("Caption Options", value.package?.caption_options),
    optionSection("Description Options", value.package?.description_options),
    optionSection("Hashtag Options", value.package?.hashtag_options),
    optionSection("Platform Copy Options", value.package?.platform_copy_options),
  ].join("");
  return `
    <div class="pill-row">${stage}</div>
    ${definitionList("Summary", compactTopLevel(value))}
    ${copySections}
    <div class="result-card">
      <h3>Raw Structured Response</h3>
      <pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>
    </div>
  `;
}

function optionSection(title, items) {
  if (!Array.isArray(items) || !items.length) return "";
  return `
    <div class="result-card">
      <h3>${escapeHtml(title)}</h3>
      <div class="result-stack">
        ${items.map((item) => copyItem(item)).join("")}
      </div>
    </div>
  `;
}

function copyItem(item) {
  const text = typeof item === "string" ? item : JSON.stringify(item, null, 2);
  return `
    <div class="copy-item">
      <p>${escapeHtml(text)}</p>
      <button type="button" class="secondary" data-copy="${escapeAttr(text)}">Copy</button>
    </div>
  `;
}

function compactTopLevel(value) {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => {
      if (Array.isArray(item)) return item.length <= 3;
      return item === null || typeof item !== "object";
    }),
  );
}

function definitionList(title, value) {
  const entries = Object.entries(value || {});
  if (!entries.length) return "";
  return `
    <div class="result-card">
      <h3>${escapeHtml(title)}</h3>
      <dl>
        ${entries
          .map(([key, val]) => {
            const rendered = typeof val === "object" ? JSON.stringify(val) : String(val);
            return `<div class="key-value"><dt>${escapeHtml(humanize(key))}</dt><dd>${escapeHtml(rendered)}</dd></div>`;
          })
          .join("")}
      </dl>
    </div>
  `;
}

function listCard(title, items) {
  if (!Array.isArray(items) || !items.length) return "";
  return `
    <div class="result-card">
      <h3>${escapeHtml(title)}</h3>
      <ul>
        ${items.map((item) => `<li>${escapeHtml(typeof item === "object" ? JSON.stringify(item) : String(item))}</li>`).join("")}
      </ul>
    </div>
  `;
}

function renderList(node, items) {
  node.innerHTML = items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
}

async function runWithOutput(label, fn) {
  showToast(label);
  try {
    await fn();
    showToast("Complete");
  } catch (error) {
    renderOutput({ error: error.message });
    showToast(error.message);
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(data.error?.message || "Request failed.");
  }
  return data;
}

function parseJsonField(selector, fallback) {
  const text = valueOf(selector);
  if (!text) return fallback;
  try {
    return JSON.parse(text);
  } catch {
    throw new Error("Metadata must be valid JSON.");
  }
}

function valueOf(selector) {
  return document.querySelector(selector)?.value?.trim() || "";
}

function setValue(selector, value) {
  const input = document.querySelector(selector);
  if (input && value !== undefined && value !== null && !input.value) {
    input.value = String(value);
  }
}

async function copyText(text) {
  await navigator.clipboard.writeText(text);
  showToast("Copied");
}

function showToast(message) {
  dom.toast.textContent = message;
  dom.toast.classList.add("visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    dom.toast.classList.remove("visible");
  }, 2200);
}

function humanize(key) {
  return key.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("\n", "&#10;");
}

const apiBase = "/api/v1";
const flashKey = "lora_flash";
const screenOrder = ["dashboard", "documents", "datasets", "training", "evaluation", "deploy", "audit"];

const screenMeta = {
  dashboard: {
    title: "Program Dashboard",
    subtitle: "Track the current model status, evaluation readiness, and operational alerts.",
  },
  documents: {
    title: "Documents",
    subtitle: "Ingest source documents with metadata so quality and PII checks can run reliably.",
  },
  datasets: {
    title: "Dataset Builder",
    subtitle: "Generate curated training sets and monitor review-queue quality before tuning.",
  },
  training: {
    title: "Training Runs",
    subtitle: "Queue LoRA runs with safe defaults, then process and monitor state progression.",
  },
  evaluation: {
    title: "Evaluation",
    subtitle: "Review go/no-go scorecards and confirm regression safety before deployment.",
  },
  deploy: {
    title: "Deploy",
    subtitle: "Promote approved run artifacts into active endpoints with explicit version control.",
  },
  audit: {
    title: "Audit Log",
    subtitle: "Inspect immutable event history for data lineage, actions, and accountability.",
  },
};

const contextState = {
  tenantName: "",
  projectName: "",
};

function readAuth() {
  return {
    token: localStorage.getItem("lora_token") || "",
    tenantId: localStorage.getItem("lora_tenant_id") || "",
    projectId: localStorage.getItem("lora_project_id") || "",
  };
}

function writeAuth(partial) {
  Object.entries(partial).forEach(([k, v]) => {
    if (v === undefined || v === null) {
      return;
    }
    const key = `lora_${k}`;
    const value = String(v).trim();
    if (!value) {
      localStorage.removeItem(key);
      return;
    }
    localStorage.setItem(key, value);
  });
}

function clearAuth() {
  localStorage.removeItem("lora_token");
  localStorage.removeItem("lora_tenant_id");
  localStorage.removeItem("lora_project_id");
}

function setFlash(message) {
  if (!message) {
    return;
  }
  sessionStorage.setItem(flashKey, message);
}

function consumeFlash() {
  const message = sessionStorage.getItem(flashKey) || "";
  if (message) {
    sessionStorage.removeItem(flashKey);
  }
  return message;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function prettyDate(value) {
  if (!value) {
    return "n/a";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }
  return parsed.toLocaleString();
}

async function api(path, options = {}) {
  const auth = readAuth();
  const headers = new Headers(options.headers || {});
  if (auth.token) {
    headers.set("Authorization", `Bearer ${auth.token}`);
  }
  if (auth.tenantId) {
    headers.set("X-Tenant-Id", auth.tenantId);
  }

  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 204) {
    return null;
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    if (response.status === 401 && window.location.pathname.startsWith("/portal")) {
      clearAuth();
      setFlash("Session expired. Please sign in again.");
      window.location.href = "/";
      throw new Error("Session expired.");
    }

    let msg = `Request failed (${response.status})`;
    if (typeof data?.detail === "string") {
      msg = data.detail;
    } else if (Array.isArray(data?.detail) && data.detail.length) {
      const first = data.detail[0];
      const fieldPath = Array.isArray(first?.loc) ? first.loc.join(".") : "";
      msg = fieldPath ? `${fieldPath}: ${first?.msg}` : first?.msg || JSON.stringify(first);
    } else if (data?.detail) {
      msg = String(data.detail);
    }
    throw new Error(msg);
  }

  return data;
}

function statusLine(nodeId, message, isError = false) {
  const node = document.getElementById(nodeId);
  if (!node) {
    return;
  }
  node.textContent = message;
  node.style.color = isError ? "#9f1239" : "#4c5d66";
}

function table(headers, rows) {
  if (!rows.length) {
    return "<p class='notice'>No records yet.</p>";
  }
  const th = headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("");
  const body = rows
    .map((row) => {
      const tds = row.map((cell) => `<td>${escapeHtml(cell ?? "")}</td>`).join("");
      return `<tr>${tds}</tr>`;
    })
    .join("");
  return `<div class='table-wrap'><table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function activeScreen() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return parts[parts.length - 1] || "dashboard";
}

function getScreenMeta(screen) {
  return (
    screenMeta[screen] || {
      title: "Workspace",
      subtitle: "Manage the selected part of your LoRA Studio workflow.",
    }
  );
}

function setBodyScreen(screen) {
  document.body.dataset.screen = screen;
}

function markActiveNav() {
  const screen = activeScreen();
  document.querySelectorAll("[data-nav]").forEach((el) => {
    el.classList.toggle("active", el.dataset.nav === screen);
  });
}

function updateSessionBadge(email) {
  const node = document.getElementById("session-user");
  if (!node) {
    return;
  }
  node.textContent = email ? `Signed in as ${email}` : "Not signed in";
}

function renderTopbar(screen) {
  const meta = getScreenMeta(screen);
  setBodyScreen(screen);

  const titleNode = document.getElementById("screen-title");
  const subtitleNode = document.getElementById("screen-subtitle");
  if (titleNode) {
    titleNode.textContent = meta.title;
  }
  if (subtitleNode) {
    subtitleNode.textContent = meta.subtitle;
  }

  const breadcrumbNode = document.getElementById("breadcrumbs");
  if (breadcrumbNode) {
    const context = contextState.projectName ? `<span>${escapeHtml(contextState.projectName)}</span>` : "";
    breadcrumbNode.innerHTML = `
      <a href="/">Home</a>
      <a href="/portal/dashboard">Portal</a>
      <span>${escapeHtml(meta.title)}</span>
      ${context}
    `;
  }

  const index = screenOrder.indexOf(screen);
  const prevScreen = index > 0 ? screenOrder[index - 1] : null;
  const nextScreen = index >= 0 && index < screenOrder.length - 1 ? screenOrder[index + 1] : null;

  const prevLink = document.getElementById("screen-prev-link");
  if (prevLink) {
    if (prevScreen) {
      prevLink.href = `/portal/${prevScreen}`;
      prevLink.textContent = `Previous: ${getScreenMeta(prevScreen).title}`;
      prevLink.style.display = "inline-flex";
    } else {
      prevLink.href = "/";
      prevLink.textContent = "Previous: Home";
      prevLink.style.display = "inline-flex";
    }
  }

  const nextLink = document.getElementById("screen-next-link");
  if (nextLink) {
    if (nextScreen) {
      nextLink.href = `/portal/${nextScreen}`;
      nextLink.textContent = `Next: ${getScreenMeta(nextScreen).title}`;
      nextLink.style.display = "inline-flex";
      nextLink.classList.remove("secondary");
    } else {
      nextLink.href = "/portal/audit";
      nextLink.textContent = "Next: Final Section";
      nextLink.style.display = "inline-flex";
      nextLink.classList.add("secondary");
    }
  }
}

function sectionIntroHtml(title, description, tips = []) {
  const tipItems = tips
    .map((tip) => `<span class="quick-tip">${escapeHtml(tip)}</span>`)
    .join("");
  return `
    <section class="section-intro">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(description)}</p>
      ${tips.length ? `<div class="quick-links">${tipItems}</div>` : ""}
    </section>
  `;
}

function missingProjectHtml() {
  return `
    <div class="content-stack">
      ${sectionIntroHtml(
        "Project Context Required",
        "Select a tenant and project from the sidebar before loading this section.",
        ["Choose tenant", "Choose project", "Click refresh"],
      )}
    </div>
  `;
}

async function bootstrapContextFromSession() {
  const me = await api("/auth/me");
  updateSessionBadge(me.email);

  if (!me.memberships.length) {
    contextState.tenantName = "";
    contextState.projectName = "";
    writeAuth({ tenant_id: "", project_id: "" });
    return me;
  }

  const auth = readAuth();
  const selectedMembership =
    me.memberships.find((m) => m.tenant_id === auth.tenantId) || me.memberships[0];
  contextState.tenantName = selectedMembership.tenant_name;
  writeAuth({ tenant_id: selectedMembership.tenant_id });

  const projects = await api("/projects");
  const selectedProject = projects.find((p) => p.id === auth.projectId) || projects[0] || null;
  contextState.projectName = selectedProject?.name || "";
  writeAuth({ project_id: selectedProject?.id || "" });
  return me;
}

function redirectToPortal() {
  window.location.href = "/portal/dashboard";
}

function redirectToLanding(message) {
  if (message) {
    setFlash(message);
  }
  window.location.href = "/";
}

async function initLanding() {
  const loginForm = document.getElementById("login-form");
  const registerForm = document.getElementById("register-form");
  const tenantForm = document.getElementById("tenant-form");
  if (!loginForm || !registerForm || !tenantForm) {
    return;
  }

  setBodyScreen("landing");

  const flash = consumeFlash();
  if (flash) {
    statusLine("auth-status", flash, true);
  }

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(loginForm);
    try {
      const result = await api("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: form.get("email"),
          password: form.get("password"),
        }),
      });
      writeAuth({ token: result.access_token });
      await bootstrapContextFromSession();
      statusLine("auth-status", "Sign-in successful. Redirecting to your dashboard.");
      redirectToPortal();
    } catch (err) {
      statusLine("auth-status", String(err.message), true);
    }
  });

  registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(registerForm);
    try {
      const result = await api("/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: form.get("email"),
          password: form.get("password"),
        }),
      });
      writeAuth({ token: result.access_token });
      await bootstrapContextFromSession();
      statusLine("auth-status", "Account created. Redirecting to your dashboard.");
      redirectToPortal();
    } catch (err) {
      statusLine("auth-status", String(err.message), true);
    }
  });

  tenantForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!readAuth().token) {
      statusLine("auth-status", "Sign in before creating a tenant workspace.", true);
      return;
    }
    const form = new FormData(tenantForm);
    try {
      const tenant = await api("/tenants", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.get("name"),
          namespace: form.get("namespace"),
        }),
      });
      writeAuth({ tenant_id: tenant.id, project_id: "" });
      statusLine("auth-status", `Workspace created: ${tenant.namespace}. Open the portal to continue.`);
    } catch (err) {
      statusLine("auth-status", String(err.message), true);
    }
  });
}

function fillSelect(selectNode, options, selectedValue) {
  if (!selectNode) {
    return;
  }
  if (!options.length) {
    selectNode.innerHTML = "<option value=''>No options</option>";
    selectNode.value = "";
    return;
  }
  selectNode.innerHTML = options
    .map((opt) => `<option value="${escapeHtml(opt.value)}">${escapeHtml(opt.label)}</option>`)
    .join("");
  if (selectedValue) {
    selectNode.value = selectedValue;
  }
}

async function loadProjectsForTenant(tenantId) {
  writeAuth({ tenant_id: tenantId });
  const projects = await api("/projects");
  const projectSelect = document.getElementById("project-select");
  const { projectId } = readAuth();
  const selectedProject = projects.find((p) => p.id === projectId) || projects[0] || null;
  contextState.projectName = selectedProject?.name || "";

  fillSelect(
    projectSelect,
    projects.map((p) => ({ value: p.id, label: `${p.name} (${p.id.slice(0, 8)})` })),
    selectedProject?.id || "",
  );

  writeAuth({ project_id: selectedProject?.id || "" });
  if (!projects.length) {
    statusLine("context-status", "No projects in this workspace yet. Create one through the API.", true);
  } else {
    statusLine("context-status", `Working in project "${selectedProject.name}" (${selectedProject.id.slice(0, 8)}).`);
  }
}

async function hydratePortalContext() {
  const me = await api("/auth/me");
  updateSessionBadge(me.email);

  const tenantSelect = document.getElementById("tenant-select");
  const projectSelect = document.getElementById("project-select");
  if (!tenantSelect || !projectSelect) {
    return;
  }

  if (!me.memberships.length) {
    contextState.tenantName = "";
    contextState.projectName = "";
    fillSelect(tenantSelect, [], "");
    fillSelect(projectSelect, [], "");
    statusLine("context-status", "No tenant membership found. Create a tenant first.", true);
    return;
  }

  const auth = readAuth();
  const selectedMembership =
    me.memberships.find((m) => m.tenant_id === auth.tenantId) || me.memberships[0];
  contextState.tenantName = selectedMembership.tenant_name;
  writeAuth({ tenant_id: selectedMembership.tenant_id });

  fillSelect(
    tenantSelect,
    me.memberships.map((m) => ({
      value: m.tenant_id,
      label: `${m.tenant_name} (${m.role})`,
    })),
    selectedMembership.tenant_id,
  );

  await loadProjectsForTenant(selectedMembership.tenant_id);

  tenantSelect.onchange = async () => {
    try {
      const selected = me.memberships.find((m) => m.tenant_id === tenantSelect.value);
      contextState.tenantName = selected?.tenant_name || "";
      await loadProjectsForTenant(tenantSelect.value);
      await renderCurrentScreen();
    } catch (err) {
      statusLine("context-status", String(err.message), true);
    }
  };

  projectSelect.onchange = () => {
    const selectedOption = projectSelect.selectedOptions[0];
    if (selectedOption) {
      const label = selectedOption.textContent || "";
      contextState.projectName = label.split(" (")[0] || "";
    }
    writeAuth({ project_id: projectSelect.value });
    statusLine("context-status", "Project context updated.");
    renderCurrentScreen();
  };
}

async function renderDashboard(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = missingProjectHtml();
    return;
  }
  const data = await api(`/projects/${projectId}/dashboard`);
  const alerts = data.alerts.length
    ? data.alerts.map((a) => `<li>${escapeHtml(a)}</li>`).join("")
    : "<li>No active alerts.</li>";
  container.innerHTML = `
    <div class="content-stack">
      ${sectionIntroHtml(
        "Operational Snapshot",
        "Use this summary to verify active adapter status and quickly detect blocked workflows.",
        ["Check alerts", "Review latest evaluation", "Validate active version"],
      )}
      <section class="panel">
        <div class="metric-grid">
          <div class="metric"><p>Active Version</p><strong>${escapeHtml(data.active_model_version || "None")}</strong></div>
          <div class="metric"><p>Latest Eval (semantic)</p><strong>${escapeHtml(data.latest_eval_score ?? "n/a")}</strong></div>
          <div class="metric"><p>Last Update</p><strong>${escapeHtml(prettyDate(data.last_update))}</strong></div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Alerts</h3>
          <p class="panel-copy">Blocking items that may require document updates, retraining, or deployment action.</p>
        </div>
        <ul>${alerts}</ul>
      </section>
    </div>
  `;
}

async function renderDocuments(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = missingProjectHtml();
    return;
  }

  const docs = await api(`/projects/${projectId}/documents`);
  container.innerHTML = `
    <div class="content-stack">
      ${sectionIntroHtml(
        "Document Intake",
        "Upload source files with metadata to power quality scoring, deduplication, and policy checks.",
        ["Upload approved documents", "Add metadata", "Confirm document status"],
      )}
      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Upload Document</h3>
          <p class="panel-copy">Recommended metadata keys: department, version, effective_date, confidentiality.</p>
        </div>
        <form id="doc-upload-form" class="inline-form">
          <label class="field-wide">Document File<input type="file" name="file" required /></label>
          <label class="field-xl">Metadata (JSON)<textarea name="metadata">{"department":"ops","effective_date":"2026-01-01"}</textarea></label>
          <button type="submit">Upload</button>
        </form>
        <p id="documents-status" class="notice"></p>
      </section>
      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Current Documents</h3>
        </div>
        ${table(
          ["ID", "Filename", "Status", "Quality", "PII Hits", "Near Duplicate"],
          docs.map((d) => [d.id, d.filename, d.status, d.quality_score, d.pii_hits.length, d.near_duplicate_of || "-"]),
        )}
      </section>
    </div>
  `;

  const form = document.getElementById("doc-upload-form");
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    try {
      const result = await api(`/projects/${projectId}/documents/upload`, {
        method: "POST",
        body: formData,
      });
      statusLine("documents-status", `Uploaded ${result.filename} (${result.status}).`);
      await renderDocuments(container);
    } catch (err) {
      statusLine("documents-status", String(err.message), true);
    }
  });
}

async function renderDatasets(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = missingProjectHtml();
    return;
  }
  const datasets = await api(`/projects/${projectId}/datasets`);
  container.innerHTML = `
    <div class="content-stack">
      ${sectionIntroHtml(
        "Dataset Curation",
        "Generate train/validation/test assets and monitor review-queue pressure before tuning.",
        ["Create a new dataset", "Review quality score", "Use latest dataset for training"],
      )}
      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Create Dataset</h3>
          <p class="panel-copy">Use semantic version naming such as dataset-v1, dataset-v2, etc.</p>
        </div>
        <form id="dataset-form" class="inline-form">
          <label class="field-wide">Dataset Name<input name="name" value="dataset-v1" required /></label>
          <button type="submit">Build Dataset</button>
        </form>
        <p id="dataset-status" class="notice"></p>
      </section>
      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Dataset Versions</h3>
        </div>
        ${table(
          ["ID", "Name", "Status", "Quality", "Total Examples", "Review Queue"],
          datasets.map((d) => [
            d.id,
            d.name,
            d.status,
            d.quality_score,
            d.stats_json?.total_examples ?? 0,
            d.stats_json?.review_examples ?? 0,
          ]),
        )}
      </section>
    </div>
  `;

  document.getElementById("dataset-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    try {
      const created = await api(`/projects/${projectId}/datasets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: form.get("name") }),
      });
      statusLine("dataset-status", `Dataset ${created.id} created (${created.status}).`);
      await renderDatasets(container);
    } catch (err) {
      statusLine("dataset-status", String(err.message), true);
    }
  });
}

async function renderTraining(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = missingProjectHtml();
    return;
  }
  const [runs, datasets] = await Promise.all([
    api(`/projects/${projectId}/runs`),
    api(`/projects/${projectId}/datasets`),
  ]);
  const latestDatasetId = datasets[0]?.id || "";

  container.innerHTML = `
    <div class="content-stack">
      ${sectionIntroHtml(
        "Training Orchestrator",
        "Queue LoRA runs, process jobs safely, and verify all transitions reach READY before deployment.",
        ["Pick dataset", "Queue run", "Process next"],
      )}
      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Queue Run</h3>
          <p class="panel-copy">Default values are tuned for RTX 4060-class memory constraints.</p>
        </div>
        <form id="run-form" class="inline-form">
          <label class="field-wide">Dataset Version ID<input name="dataset_version_id" value="${escapeHtml(latestDatasetId)}" required /></label>
          <label class="field-wide">Base Model
            <select name="base_model_id">
              <option value="mistralai/Mistral-7B-Instruct-v0.3">Mistral 7B Instruct v0.3</option>
              <option value="meta-llama/Llama-3.1-8B-Instruct">Llama 3.1 8B Instruct</option>
              <option value="Qwen/Qwen2.5-7B-Instruct">Qwen2.5 7B Instruct</option>
            </select>
          </label>
          <button type="submit">Queue Training Run</button>
          <button class="secondary" type="button" id="process-next">Process Next Run</button>
        </form>
        <p id="run-status" class="notice"></p>
      </section>
      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Run History</h3>
        </div>
        ${table(
          ["ID", "State", "Progress", "VRAM", "Dataset", "Eval", "Error"],
          runs.map((r) => [
            r.id,
            r.state,
            `${Math.round((r.progress || 0) * 100)}%`,
            `${r.vram_estimate_gb}GB`,
            r.dataset_version_id,
            r.eval_report_id || "-",
            r.error_message || "-",
          ]),
        )}
      </section>
    </div>
  `;

  document.getElementById("run-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    const payload = {
      dataset_version_id: form.get("dataset_version_id"),
      base_model_id: form.get("base_model_id"),
      data_rights_confirmed: true,
      config: {
        lora_rank: 16,
        lora_alpha: 32,
        lora_dropout: 0.05,
        sequence_length: 1024,
        per_device_batch_size: 1,
        gradient_accumulation_steps: 8,
        precision: "bf16",
        epochs: 3,
        max_steps: 0,
        save_every_steps: 100,
        use_4bit: true,
      },
    };
    try {
      const run = await api(`/projects/${projectId}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      statusLine("run-status", `Run queued: ${run.id}.`);
      await renderTraining(container);
    } catch (err) {
      statusLine("run-status", String(err.message), true);
    }
  });

  document.getElementById("process-next")?.addEventListener("click", async () => {
    try {
      const run = await api("/runs/process-next", { method: "POST" });
      statusLine("run-status", run ? `Processed run ${run.id} -> ${run.state}.` : "No queued runs.");
      await renderTraining(container);
    } catch (err) {
      statusLine("run-status", String(err.message), true);
    }
  });
}

async function renderEvaluation(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = missingProjectHtml();
    return;
  }
  const reports = await api(`/projects/${projectId}/evaluations`);
  container.innerHTML = `
    <div class="content-stack">
      ${sectionIntroHtml(
        "Evaluation Reports",
        "Compare run quality and confirm go/no-go decisions with clear measurable evidence.",
        ["Review semantic score", "Check unsupported-claim rate", "Confirm go/no-go"],
      )}
      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Evaluation History</h3>
        </div>
        ${table(
          ["ID", "Run", "Decision", "Exact Match", "Semantic Similarity", "Unsupported Claims", "Created"],
          reports.map((r) => [
            r.id,
            r.training_run_id,
            r.go_no_go ? "GO" : "NO-GO",
            r.metrics_json.exact_match,
            r.metrics_json.semantic_similarity,
            r.metrics_json.unsupported_claim_rate,
            prettyDate(r.created_at),
          ]),
        )}
      </section>
    </div>
  `;
}

async function renderDeploy(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = missingProjectHtml();
    return;
  }

  const [deployments, runs] = await Promise.all([
    api(`/projects/${projectId}/deployments`),
    api(`/projects/${projectId}/runs`),
  ]);

  const latestReadyRun = runs.find((r) => r.state === "ready")?.id || "";

  container.innerHTML = `
    <div class="content-stack">
      ${sectionIntroHtml(
        "Deployment Control",
        "Promote a verified run into active service and preserve endpoint/version traceability.",
        ["Choose READY run", "Set version tag", "Activate endpoint"],
      )}
      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Activate Deployment</h3>
          <p class="panel-copy">Only READY runs should be promoted to production endpoints.</p>
        </div>
        <form id="deploy-form" class="inline-form">
          <label class="field-wide">Training Run ID<input name="training_run_id" value="${escapeHtml(latestReadyRun)}" required /></label>
          <label class="field-wide">Version Tag<input name="version" value="v1" required /></label>
          <label class="field-xl">Endpoint URL<input name="endpoint_url" value="http://localhost:8000/api/v1/inference/chat" /></label>
          <button type="submit">Activate Deployment</button>
        </form>
        <p id="deploy-status" class="notice"></p>
      </section>
      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Deployment History</h3>
        </div>
        ${table(
          ["ID", "Version", "Status", "Run", "Endpoint", "Created"],
          deployments.map((d) => [d.id, d.version, d.status, d.training_run_id, d.endpoint_url || "-", prettyDate(d.created_at)]),
        )}
      </section>
    </div>
  `;

  document.getElementById("deploy-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    const payload = {
      training_run_id: form.get("training_run_id"),
      version: form.get("version"),
      endpoint_url: form.get("endpoint_url"),
    };
    try {
      const deployment = await api(`/projects/${projectId}/deployments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      statusLine("deploy-status", `Deployment active: ${deployment.version}.`);
      await renderDeploy(container);
    } catch (err) {
      statusLine("deploy-status", String(err.message), true);
    }
  });
}

async function renderAudit(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = missingProjectHtml();
    return;
  }
  const events = await api(`/projects/${projectId}/audit`);
  container.innerHTML = `
    <div class="content-stack">
      ${sectionIntroHtml(
        "Audit Timeline",
        "Review immutable action history by user, entity, and timestamp for compliance and debugging.",
        ["Trace changes", "Review user actions", "Verify lineage"],
      )}
      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">Recent Events</h3>
        </div>
        ${table(
          ["Time", "Action", "Entity", "Entity ID", "User", "Details"],
          events.map((e) => [
            prettyDate(e.created_at),
            e.action,
            e.entity_type,
            e.entity_id || "-",
            e.user_id || "-",
            JSON.stringify(e.details_json || {}),
          ]),
        )}
      </section>
    </div>
  `;
}

async function renderCurrentScreen() {
  const container = document.getElementById("screen-content");
  if (!container) {
    return;
  }

  const screen = activeScreen();
  markActiveNav();
  renderTopbar(screen);

  try {
    if (screen === "dashboard") {
      await renderDashboard(container);
    } else if (screen === "documents") {
      await renderDocuments(container);
    } else if (screen === "datasets") {
      await renderDatasets(container);
    } else if (screen === "training") {
      await renderTraining(container);
    } else if (screen === "evaluation") {
      await renderEvaluation(container);
    } else if (screen === "deploy") {
      await renderDeploy(container);
    } else if (screen === "audit") {
      await renderAudit(container);
    } else {
      container.innerHTML = `<p class="notice">Unknown screen: ${escapeHtml(screen)}</p>`;
    }
  } catch (err) {
    container.innerHTML = `<p class="notice" style="color:#9f1239">${escapeHtml(String(err.message))}</p>`;
  }
}

function bindPortalShellEvents() {
  document.getElementById("refresh-screen")?.addEventListener("click", async () => {
    await hydratePortalContext();
    await renderCurrentScreen();
  });

  document.getElementById("logout-btn")?.addEventListener("click", () => {
    clearAuth();
    redirectToLanding("Signed out.");
  });

  document.getElementById("back-btn")?.addEventListener("click", () => {
    if (window.history.length > 1) {
      window.history.back();
      return;
    }
    window.location.href = "/portal/dashboard";
  });
}

async function initPortal() {
  const content = document.getElementById("screen-content");
  if (!content) {
    return;
  }
  if (!readAuth().token) {
    redirectToLanding("Sign in to access the portal.");
    return;
  }

  bindPortalShellEvents();

  try {
    await hydratePortalContext();
    await renderCurrentScreen();
  } catch (err) {
    statusLine("context-status", String(err.message), true);
  }
}

window.addEventListener("DOMContentLoaded", async () => {
  await initLanding();
  await initPortal();
});

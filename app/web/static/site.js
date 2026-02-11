const apiBase = "/api/v1";
const flashKey = "lora_flash";

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
  node.style.color = isError ? "#9f1239" : "#5b6770";
}

function table(headers, rows) {
  if (!rows.length) {
    return "<p class='notice'>No records yet.</p>";
  }
  const th = headers.map((h) => `<th>${h}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${row.map((cell) => `<td>${cell ?? ""}</td>`).join("")}</tr>`)
    .join("");
  return `<div class='table-wrap'><table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function activeScreen() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return parts[parts.length - 1] || "dashboard";
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
  node.textContent = email ? `Signed in: ${email}` : "Not signed in";
}

async function bootstrapContextFromSession() {
  const me = await api("/auth/me");
  updateSessionBadge(me.email);

  if (!me.memberships.length) {
    writeAuth({ tenant_id: "", project_id: "" });
    return me;
  }

  const auth = readAuth();
  const selectedMembership =
    me.memberships.find((m) => m.tenant_id === auth.tenantId) || me.memberships[0];
  writeAuth({ tenant_id: selectedMembership.tenant_id });

  const projects = await api("/projects");
  const selectedProject =
    projects.find((p) => p.id === auth.projectId) || projects[0] || null;
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
      statusLine("auth-status", "Login successful. Redirecting to portal.");
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
      statusLine("auth-status", "Registration successful. Redirecting to portal.");
      redirectToPortal();
    } catch (err) {
      statusLine("auth-status", String(err.message), true);
    }
  });

  tenantForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!readAuth().token) {
      statusLine("auth-status", "Sign in before creating a tenant.", true);
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
      statusLine("auth-status", `Tenant created: ${tenant.namespace}. Open portal to create a project.`);
    } catch (err) {
      statusLine("auth-status", String(err.message), true);
    }
  });
}

function fillSelect(selectNode, options, selectedValue) {
  if (!selectNode) {
    return;
  }
  selectNode.innerHTML = options
    .map((opt) => `<option value="${opt.value}">${opt.label}</option>`)
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
  const selected = projects.find((p) => p.id === projectId) || projects[0] || null;
  fillSelect(
    projectSelect,
    projects.map((p) => ({ value: p.id, label: `${p.name} (${p.id.slice(0, 8)})` })),
    selected?.id || "",
  );
  writeAuth({ project_id: selected?.id || "" });
  if (!projects.length) {
    statusLine("context-status", "No projects in this tenant yet. Create one via API.", true);
  } else {
    statusLine("context-status", `Using project ${selected.id.slice(0, 8)} in tenant ${tenantId.slice(0, 8)}.`);
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
    fillSelect(tenantSelect, [], "");
    fillSelect(projectSelect, [], "");
    statusLine("context-status", "No tenant membership found. Create a tenant first.", true);
    return;
  }

  const auth = readAuth();
  const selectedMembership =
    me.memberships.find((m) => m.tenant_id === auth.tenantId) || me.memberships[0];
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
      await loadProjectsForTenant(tenantSelect.value);
      await renderCurrentScreen();
    } catch (err) {
      statusLine("context-status", String(err.message), true);
    }
  };

  projectSelect.onchange = () => {
    writeAuth({ project_id: projectSelect.value });
    statusLine("context-status", "Project updated.");
    renderCurrentScreen();
  };
}

async function renderDashboard(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = "<p class='notice'>Select a project to load dashboard data.</p>";
    return;
  }
  const data = await api(`/projects/${projectId}/dashboard`);
  const alerts = data.alerts.length ? data.alerts.map((a) => `<li>${a}</li>`).join("") : "<li>No alerts</li>";
  container.innerHTML = `
    <div class='card-grid'>
      <div class='metric'><p>Active Version</p><strong>${data.active_model_version || "None"}</strong></div>
      <div class='metric'><p>Latest Eval (semantic)</p><strong>${data.latest_eval_score ?? "n/a"}</strong></div>
      <div class='metric'><p>Last Update</p><strong>${data.last_update || "n/a"}</strong></div>
    </div>
    <div class='metric' style='margin-top:12px'>
      <p>Alerts</p>
      <ul>${alerts}</ul>
    </div>
  `;
}

async function renderDocuments(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = "<p class='notice'>Select a project first.</p>";
    return;
  }

  const docs = await api(`/projects/${projectId}/documents`);
  container.innerHTML = `
    <form id='doc-upload-form' class='inline-form'>
      <label>File<input type='file' name='file' required /></label>
      <label>Metadata JSON<textarea name='metadata'>{"department":"ops","effective_date":"2026-01-01"}</textarea></label>
      <button type='submit'>Upload Document</button>
    </form>
    <p id='documents-status' class='notice'></p>
    ${table(
      ["ID", "Filename", "Status", "Quality", "PII Hits", "Near Duplicate"],
      docs.map((d) => [d.id, d.filename, d.status, d.quality_score, d.pii_hits.length, d.near_duplicate_of || "-"]),
    )}
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
      statusLine("documents-status", `Uploaded ${result.filename} (${result.status})`);
      await renderDocuments(container);
    } catch (err) {
      statusLine("documents-status", String(err.message), true);
    }
  });
}

async function renderDatasets(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = "<p class='notice'>Select a project first.</p>";
    return;
  }
  const datasets = await api(`/projects/${projectId}/datasets`);
  container.innerHTML = `
    <form id='dataset-form' class='inline-form'>
      <label>Dataset Name<input name='name' value='dataset-v1' required /></label>
      <button type='submit'>Build Dataset</button>
    </form>
    <p id='dataset-status' class='notice'></p>
    ${table(
      ["ID", "Name", "Status", "Quality", "Total", "Review Queue"],
      datasets.map((d) => [
        d.id,
        d.name,
        d.status,
        d.quality_score,
        d.stats_json?.total_examples ?? 0,
        d.stats_json?.review_examples ?? 0,
      ]),
    )}
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
      statusLine("dataset-status", `Dataset ${created.id} created (${created.status})`);
      await renderDatasets(container);
    } catch (err) {
      statusLine("dataset-status", String(err.message), true);
    }
  });
}

async function renderTraining(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = "<p class='notice'>Select a project first.</p>";
    return;
  }
  const [runs, datasets] = await Promise.all([
    api(`/projects/${projectId}/runs`),
    api(`/projects/${projectId}/datasets`),
  ]);
  const latestDatasetId = datasets[0]?.id || "";

  container.innerHTML = `
    <form id='run-form' class='inline-form'>
      <label>Dataset ID<input name='dataset_version_id' value='${latestDatasetId}' required /></label>
      <label>Base Model
        <select name='base_model_id'>
          <option value='mistralai/Mistral-7B-Instruct-v0.3'>Mistral 7B Instruct v0.3</option>
          <option value='meta-llama/Llama-3.1-8B-Instruct'>Llama 3.1 8B Instruct</option>
          <option value='Qwen/Qwen2.5-7B-Instruct'>Qwen2.5 7B Instruct</option>
        </select>
      </label>
      <button type='submit'>Queue Training Run</button>
      <button class='secondary' type='button' id='process-next'>Process Next Run</button>
    </form>
    <p id='run-status' class='notice'></p>
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
      statusLine("run-status", `Run queued: ${run.id}`);
      await renderTraining(container);
    } catch (err) {
      statusLine("run-status", String(err.message), true);
    }
  });

  document.getElementById("process-next")?.addEventListener("click", async () => {
    try {
      const run = await api("/runs/process-next", { method: "POST" });
      statusLine("run-status", run ? `Processed run ${run.id} -> ${run.state}` : "No queued runs.");
      await renderTraining(container);
    } catch (err) {
      statusLine("run-status", String(err.message), true);
    }
  });
}

async function renderEvaluation(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = "<p class='notice'>Select a project first.</p>";
    return;
  }
  const reports = await api(`/projects/${projectId}/evaluations`);
  container.innerHTML = table(
    ["ID", "Run", "Go/No-Go", "Exact", "Semantic", "Unsupported", "Created"],
    reports.map((r) => [
      r.id,
      r.training_run_id,
      r.go_no_go ? "GO" : "NO-GO",
      r.metrics_json.exact_match,
      r.metrics_json.semantic_similarity,
      r.metrics_json.unsupported_claim_rate,
      r.created_at,
    ]),
  );
}

async function renderDeploy(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = "<p class='notice'>Select a project first.</p>";
    return;
  }

  const [deployments, runs] = await Promise.all([
    api(`/projects/${projectId}/deployments`),
    api(`/projects/${projectId}/runs`),
  ]);

  const latestReadyRun = runs.find((r) => r.state === "ready")?.id || "";

  container.innerHTML = `
    <form id='deploy-form' class='inline-form'>
      <label>Training Run ID<input name='training_run_id' value='${latestReadyRun}' required /></label>
      <label>Version<input name='version' value='v1' required /></label>
      <label>Endpoint URL<input name='endpoint_url' value='http://localhost:8000/api/v1/inference/chat' /></label>
      <button type='submit'>Activate Deployment</button>
    </form>
    <p id='deploy-status' class='notice'></p>
    ${table(
      ["ID", "Version", "Status", "Run", "Endpoint", "Created"],
      deployments.map((d) => [d.id, d.version, d.status, d.training_run_id, d.endpoint_url || "-", d.created_at]),
    )}
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
      statusLine("deploy-status", `Deployment active: ${deployment.version}`);
      await renderDeploy(container);
    } catch (err) {
      statusLine("deploy-status", String(err.message), true);
    }
  });
}

async function renderAudit(container) {
  const { projectId } = readAuth();
  if (!projectId) {
    container.innerHTML = "<p class='notice'>Select a project first.</p>";
    return;
  }
  const events = await api(`/projects/${projectId}/audit`);
  container.innerHTML = table(
    ["Time", "Action", "Entity", "Entity ID", "User", "Details"],
    events.map((e) => [
      e.created_at,
      e.action,
      e.entity_type,
      e.entity_id || "-",
      e.user_id || "-",
      JSON.stringify(e.details_json || {}),
    ]),
  );
}

async function renderCurrentScreen() {
  const container = document.getElementById("screen-content");
  if (!container) {
    return;
  }

  const screen = activeScreen();
  const title = document.getElementById("screen-title");
  if (title) {
    title.textContent = screen.charAt(0).toUpperCase() + screen.slice(1);
  }

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
      container.innerHTML = "<p class='notice'>Unknown screen.</p>";
    }
  } catch (err) {
    container.innerHTML = `<p class='notice' style='color:#9f1239'>${String(err.message)}</p>`;
  }
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
  markActiveNav();
  document.getElementById("refresh-screen")?.addEventListener("click", async () => {
    await hydratePortalContext();
    await renderCurrentScreen();
  });
  document.getElementById("logout-btn")?.addEventListener("click", () => {
    clearAuth();
    redirectToLanding("Signed out.");
  });

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

let activeJobId = null;
let pollTimer = null;
let tailorJobRunning = false;
let compileRunning = false;

const LOCAL_KEYS = {
  resume: "rts_resume_latex",
  instructions: "rts_instructions_text",
};

const MODEL_OPTIONS = {
  openai: ["gpt-5", "gpt-5-mini", "gpt-5.2"],
  gemini: ["gemini-2.5-flash", "gemini-2.5-pro"],
};

let builderState = {
  hardLocks: [],
  modules: [],
  roles: [],
  workflow: [],
};

function readLocal(key, fallback = "") {
  try {
    const value = localStorage.getItem(key);
    return value == null ? fallback : value;
  } catch (_err) {
    return fallback;
  }
}

function writeLocal(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (_err) {
    // Ignore storage failures.
  }
}

function removeLocal(key) {
  try {
    localStorage.removeItem(key);
  } catch (_err) {
    // Ignore storage failures.
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Request failed: ${res.status}`);
  }

  return res.json();
}

function setStatus(message) {
  document.getElementById("statusLine").textContent = message;
}

function setSourcePill(text) {
  document.getElementById("sourcePill").textContent = text;
}

function setProgress(percent, label) {
  const pct = Math.max(0, Math.min(100, Number(percent) || 0));
  document.getElementById("progressFill").style.width = `${pct}%`;
  document.getElementById("progressPct").textContent = `${pct}%`;
  document.getElementById("progressLabel").textContent = label || "Progress";
}

function refreshPreview() {
  const frame = document.getElementById("pdfFrame");
  const ts = Date.now();
  frame.src = `/api/pdf/latest?t=${ts}#toolbar=0&navpanes=0&scrollbar=0&pagemode=none&zoom=page-width`;
}

function setupTabs() {
  const tabs = document.querySelectorAll(".tab");
  const panels = document.querySelectorAll(".tab-panel");

  tabs.forEach((tabBtn) => {
    tabBtn.addEventListener("click", () => {
      const target = tabBtn.dataset.tab;
      tabs.forEach((t) => t.classList.remove("active"));
      panels.forEach((p) => p.classList.remove("active"));
      tabBtn.classList.add("active");
      document.getElementById(target).classList.add("active");
    });
  });
}

function setupBuilderTabs() {
  const tabs = document.querySelectorAll(".builder-subtab");
  const panels = document.querySelectorAll(".builder-panel");
  if (!tabs.length || !panels.length) return;

  tabs.forEach((tabBtn) => {
    tabBtn.addEventListener("click", () => {
      const target = tabBtn.dataset.builderTab;
      tabs.forEach((t) => t.classList.remove("active"));
      panels.forEach((p) => p.classList.remove("active"));
      tabBtn.classList.add("active");
      const panel = document.getElementById(target);
      if (panel) panel.classList.add("active");
    });
  });
}

function setTailorRunning(running) {
  tailorJobRunning = Boolean(running);
  const btn = document.getElementById("tailorBtn");
  if (!btn) return;
  btn.disabled = tailorJobRunning;
  btn.textContent = tailorJobRunning ? "Tailoring..." : "Run Multi-Agent Tailor";
}

function setSessionKeyMeta(hasKey, provider = "") {
  const el = document.getElementById("sessionKeyMeta");
  if (!hasKey) {
    el.textContent = "Session key: not set";
    return;
  }
  el.textContent = `Session key: set (${provider || "provider unknown"})`;
}

async function loadSessionKeyStatus() {
  const status = await api("/api/session/status", { method: "GET" });
  setSessionKeyMeta(Boolean(status.has_key), status.provider || "");
}

function populateModelSelect(provider, selectedModel) {
  const modelSelect = document.getElementById("modelSelect");
  const options = MODEL_OPTIONS[provider] || [];
  modelSelect.innerHTML = "";

  options.forEach((model) => {
    const opt = document.createElement("option");
    opt.value = model;
    opt.textContent = model;
    modelSelect.appendChild(opt);
  });

  if (selectedModel && options.includes(selectedModel)) {
    modelSelect.value = selectedModel;
  } else if (options.length > 0) {
    modelSelect.value = options[0];
  }
}

async function refreshModelsForProvider(provider, selectedModel = "") {
  try {
    const payload = await api(`/api/models?provider=${encodeURIComponent(provider)}`, { method: "GET" });
    if (payload && Array.isArray(payload.models) && payload.models.length > 0) {
      MODEL_OPTIONS[provider] = payload.models;
    }
  } catch (_err) {
    // Keep fallback list when discovery fails.
  }
  populateModelSelect(provider, selectedModel);
}

function parseWorkflowStepsFromText(content) {
  const match = content.match(/Workflow \(when user provides JD \+ LaTeX\)([\s\S]*)$/m);
  if (!match) return [];
  const lines = match[1].split("\n");
  return lines
    .map((line) => line.match(/^\s*\d+\)\s*(.+)\s*$/))
    .filter(Boolean)
    .map((m) => m[1]);
}

function extractStructuredConfigFromText(content) {
  const match = content.match(/```json\s*([\s\S]*?)\s*```/i);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[1]);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch (_err) {
    return null;
  }
}

function normalizeBuilderFromConfig(config) {
  const modules = Object.entries(config.modules || {}).map(([key, value]) => ({
    key,
    rulesText: Array.isArray(value) ? value.join("\n") : String(value || ""),
  }));

  const roles = Object.entries(config.roles || {}).map(([key, value]) => ({
    key,
    name: String(value.name || ""),
    mode: String(value.mode || "json").toLowerCase() === "latex" ? "latex" : "json",
    modulesText: Array.isArray(value.modules) ? value.modules.join(", ") : "",
    instruction: String(value.instruction || ""),
  }));

  const workflow = Array.isArray(config.workflow)
    ? config.workflow.map((w) => ({ step: String(w.step || ""), role: String(w.role || "") }))
    : [];

  const hardLocks = Array.isArray(config.global_hard_locks) ? config.global_hard_locks.map(String) : [];
  return { hardLocks, modules, roles, workflow };
}

function makeDefaultBuilderFromLegacyText(content) {
  const legacySteps = parseWorkflowStepsFromText(content || "");
  return {
    hardLocks: [],
    modules: [],
    roles: [],
    workflow: legacySteps.map((step) => ({ step, role: "" })),
  };
}

function builderToStructuredConfig() {
  const moduleMap = {};
  builderState.modules.forEach((m) => {
    const key = (m.key || "").trim();
    if (!key) return;
    moduleMap[key] = (m.rulesText || "")
      .split("\n")
      .map((x) => x.trim())
      .filter((x) => x.length > 0);
  });

  const roleMap = {};
  builderState.roles.forEach((r) => {
    const key = (r.key || "").trim();
    if (!key) return;
    roleMap[key] = {
      name: (r.name || "").trim() || key,
      mode: r.mode === "latex" ? "latex" : "json",
      modules: (r.modulesText || "")
        .split(",")
        .map((x) => x.trim())
        .filter((x) => x.length > 0),
      instruction: (r.instruction || "").trim(),
    };
  });

  const workflow = builderState.workflow
    .map((w) => ({ step: (w.step || "").trim(), role: (w.role || "").trim() }))
    .filter((w) => w.step.length > 0);

  return {
    version: 1,
    global_hard_locks: builderState.hardLocks.map((x) => x.trim()).filter((x) => x.length > 0),
    modules: moduleMap,
    roles: roleMap,
    workflow,
  };
}

function structuredConfigToText(config) {
  return `Resume Tailor GPT - Structured Instructions\n\n\`\`\`json\n${JSON.stringify(config, null, 2)}\n\`\`\`\n\nHuman note:\n- This file is structured for role-based orchestration.\n- Keep JSON valid to ensure parser compatibility.\n`;
}

function renderBuilder() {
  const hardLocksInput = document.getElementById("hardLocksInput");
  hardLocksInput.value = (builderState.hardLocks || []).join("\n");

  const moduleRoot = document.getElementById("moduleItems");
  moduleRoot.innerHTML = "";
  builderState.modules.forEach((m, idx) => {
    const wrap = document.createElement("div");
    wrap.className = "builder-item";

    const keyLabel = document.createElement("label");
    keyLabel.textContent = "Module Key";
    const keyInput = document.createElement("input");
    keyInput.type = "text";
    keyInput.value = m.key || "";

    const rulesLabel = document.createElement("label");
    rulesLabel.textContent = "Rules (one per line)";
    const rulesArea = document.createElement("textarea");
    rulesArea.className = "builder-area";
    rulesArea.value = m.rulesText || "";

    const row = document.createElement("div");
    row.className = "row compact";
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "Delete Module";
    row.appendChild(del);

    keyInput.addEventListener("input", (e) => {
      builderState.modules[idx].key = e.target.value;
    });
    rulesArea.addEventListener("input", (e) => {
      builderState.modules[idx].rulesText = e.target.value;
    });
    del.addEventListener("click", () => {
      builderState.modules.splice(idx, 1);
      renderBuilder();
    });

    wrap.appendChild(keyLabel);
    wrap.appendChild(keyInput);
    wrap.appendChild(rulesLabel);
    wrap.appendChild(rulesArea);
    wrap.appendChild(row);
    moduleRoot.appendChild(wrap);
  });

  const roleRoot = document.getElementById("roleItems");
  roleRoot.innerHTML = "";
  builderState.roles.forEach((r, idx) => {
    const wrap = document.createElement("div");
    wrap.className = "builder-item";

    const rkLabel = document.createElement("label");
    rkLabel.textContent = "Role Key";
    const rk = document.createElement("input");
    rk.type = "text";
    rk.value = r.key || "";

    const rnLabel = document.createElement("label");
    rnLabel.textContent = "Role Name";
    const rn = document.createElement("input");
    rn.type = "text";
    rn.value = r.name || "";

    const rmLabel = document.createElement("label");
    rmLabel.textContent = "Mode";
    const rm = document.createElement("select");
    ["json", "latex"].forEach((mode) => {
      const opt = document.createElement("option");
      opt.value = mode;
      opt.textContent = mode;
      rm.appendChild(opt);
    });
    rm.value = r.mode === "latex" ? "latex" : "json";

    const modsLabel = document.createElement("label");
    modsLabel.textContent = "Modules (comma-separated keys)";
    const mods = document.createElement("input");
    mods.type = "text";
    mods.value = r.modulesText || "";

    const instrLabel = document.createElement("label");
    instrLabel.textContent = "Instruction";
    const instr = document.createElement("textarea");
    instr.className = "builder-area";
    instr.value = r.instruction || "";

    const row = document.createElement("div");
    row.className = "row compact";
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "Delete Role";
    row.appendChild(del);

    rk.addEventListener("input", (e) => { builderState.roles[idx].key = e.target.value; });
    rn.addEventListener("input", (e) => { builderState.roles[idx].name = e.target.value; });
    rm.addEventListener("change", (e) => { builderState.roles[idx].mode = e.target.value; });
    mods.addEventListener("input", (e) => { builderState.roles[idx].modulesText = e.target.value; });
    instr.addEventListener("input", (e) => { builderState.roles[idx].instruction = e.target.value; });
    del.addEventListener("click", () => {
      builderState.roles.splice(idx, 1);
      renderBuilder();
    });

    wrap.appendChild(rkLabel);
    wrap.appendChild(rk);
    wrap.appendChild(rnLabel);
    wrap.appendChild(rn);
    wrap.appendChild(rmLabel);
    wrap.appendChild(rm);
    wrap.appendChild(modsLabel);
    wrap.appendChild(mods);
    wrap.appendChild(instrLabel);
    wrap.appendChild(instr);
    wrap.appendChild(row);
    roleRoot.appendChild(wrap);
  });

  const workflowRoot = document.getElementById("workflowItems");
  workflowRoot.innerHTML = "";
  const roleKeys = builderState.roles.map((r) => (r.key || "").trim()).filter((k) => k.length > 0);
  builderState.workflow.forEach((w, idx) => {
    const wrap = document.createElement("div");
    wrap.className = "builder-item";

    const stepLabel = document.createElement("label");
    stepLabel.textContent = "Step";
    const stepInput = document.createElement("input");
    stepInput.type = "text";
    stepInput.value = w.step || "";

    const roleLabel = document.createElement("label");
    roleLabel.textContent = "Role";
    const roleSelect = document.createElement("select");
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "(select role)";
    roleSelect.appendChild(empty);
    roleKeys.forEach((key) => {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = key;
      roleSelect.appendChild(opt);
    });
    roleSelect.value = w.role || "";

    const row = document.createElement("div");
    row.className = "row compact";
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "Delete Step";
    row.appendChild(del);

    stepInput.addEventListener("input", (e) => { builderState.workflow[idx].step = e.target.value; });
    roleSelect.addEventListener("change", (e) => { builderState.workflow[idx].role = e.target.value; });
    del.addEventListener("click", () => {
      builderState.workflow.splice(idx, 1);
      renderBuilder();
    });

    wrap.appendChild(stepLabel);
    wrap.appendChild(stepInput);
    wrap.appendChild(roleLabel);
    wrap.appendChild(roleSelect);
    wrap.appendChild(row);
    workflowRoot.appendChild(wrap);
  });
}

function loadBuilderFromRulesText() {
  const content = document.getElementById("instructionsInput").value || "";
  const structured = extractStructuredConfigFromText(content);
  builderState = structured ? normalizeBuilderFromConfig(structured) : makeDefaultBuilderFromLegacyText(content);
  renderBuilder();
  setStatus(structured ? "Loaded builder from structured rules." : "No structured JSON found; loaded legacy workflow steps.");
}

function applyBuilderToRulesText() {
  builderState.hardLocks = (document.getElementById("hardLocksInput").value || "")
    .split("\n")
    .map((x) => x.trim())
    .filter((x) => x.length > 0);

  const config = builderToStructuredConfig();
  const roleKeys = new Set(Object.keys(config.roles || {}));
  const invalid = (config.workflow || []).find((w) => w.role && !roleKeys.has(w.role));
  if (invalid) {
    setStatus(`Workflow role "${invalid.role}" is not defined in Roles.`);
    return false;
  }

  const text = structuredConfigToText(config);
  document.getElementById("instructionsInput").value = text;
  writeLocal(LOCAL_KEYS.instructions, text);
  renderBuilder();
  setStatus("Applied builder into structured rules text.");
  return true;
}

async function loadInstructions() {
  const payload = await api("/api/instructions", { method: "GET" });
  const localInstructions = readLocal(LOCAL_KEYS.instructions, "");
  const activeInstructions = localInstructions || payload.content || "";
  document.getElementById("instructionsInput").value = activeInstructions;
  document.getElementById("instructionsMeta").textContent = `Source: ${payload.source} | Path: ${payload.path}`;
  loadBuilderFromRulesText();
}

async function saveInstructions() {
  const content = document.getElementById("instructionsInput").value;
  const payload = await api("/api/instructions", {
    method: "PUT",
    body: JSON.stringify({ content }),
  });

  document.getElementById("instructionsMeta").textContent = `Source: ${payload.source} | Path: ${payload.path}`;
  writeLocal(LOCAL_KEYS.instructions, content);
  loadBuilderFromRulesText();
  setStatus("Custom rules saved.");
  setSourcePill(`Instructions source: ${payload.source}`);
}

async function resetInstructions() {
  const payload = await api("/api/instructions/reset", { method: "POST" });
  document.getElementById("instructionsInput").value = payload.content || "";
  document.getElementById("instructionsMeta").textContent = `Source: ${payload.source} | Path: ${payload.path}`;
  removeLocal(LOCAL_KEYS.instructions);
  loadBuilderFromRulesText();
  setStatus("Reset to default rules file.");
  setSourcePill("Instructions source: default");
}

async function loadState() {
  const state = await api("/api/state", { method: "GET" });
  const localResume = readLocal(LOCAL_KEYS.resume, "");
  const activeResume = localResume || state.resume_latex || "";
  document.getElementById("resumeInput").value = activeResume;
  document.getElementById("latexOutput").value = activeResume;
  const provider = state.llm_provider || "openai";
  document.getElementById("providerSelect").value = provider;
  const selectedModel = provider === "gemini" ? (state.llm_gemini_model || "gemini-2.5-flash") : (state.llm_model || "gpt-5");
  await refreshModelsForProvider(provider, selectedModel);

  setStatus(`LLM: ${state.llm_enabled ? "enabled" : "disabled"} | PDF: ${state.pdf_available ? "available" : "not compiled"}`);
  setSourcePill(`Instructions source: ${state.instructions_source} | ${state.instructions_path}`);

  if (state.pdf_available) {
    refreshPreview();
  }

  await loadInstructions();
  await loadSessionKeyStatus();
}

async function saveResume() {
  const resume = document.getElementById("resumeInput").value;
  await api("/api/resume", {
    method: "PUT",
    body: JSON.stringify({ resume_latex: resume }),
  });
  document.getElementById("latexOutput").value = resume;
  writeLocal(LOCAL_KEYS.resume, resume);
  setStatus("Resume cache saved.");
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollJobStatus() {
  if (!activeJobId) return;
  const job = await api(`/api/tailor/status/${activeJobId}`, { method: "GET" });
  setProgress(job.progress, job.stage);
  setStatus(`Tailor job ${job.status}: ${job.stage}`);
  if (job.jd_analysis) {
    document.getElementById("analysisOutput").value = job.jd_analysis;
  }

  if (job.status === "completed") {
    document.getElementById("latexOutput").value = job.latex || "";
    document.getElementById("resumeInput").value = job.latex || "";
    stopPolling();
    activeJobId = null;
    setTailorRunning(false);
    setStatus("Tailoring complete.");
    return;
  }

  if (job.status === "failed") {
    stopPolling();
    activeJobId = null;
    setTailorRunning(false);
    setStatus(`Tailoring failed: ${job.error || "Unknown error"}`);
  }
}

async function tailorResume() {
  if (tailorJobRunning) {
    setStatus("A tailor job is already running.");
    return;
  }

  const jd = document.getElementById("jdInput").value.trim();
  const llmProvider = document.getElementById("providerSelect").value;
  const llmModel = document.getElementById("modelSelect").value;
  if (!jd) {
    setStatus("Paste a job description first.");
    return;
  }

  stopPolling();
  setTailorRunning(true);
  setProgress(0, "Queued");
  setStatus("Starting tailor job...");
  try {
    const start = await api("/api/tailor/start", {
      method: "POST",
      body: JSON.stringify({
        job_description: jd,
        llm_provider: llmProvider,
        llm_model: llmModel || null,
      }),
    });

    activeJobId = start.job_id;
    await pollJobStatus();
    pollTimer = setInterval(() => {
      pollJobStatus().catch((err) => {
        stopPolling();
        activeJobId = null;
        setTailorRunning(false);
        setStatus(`Progress polling failed: ${err.message}`);
      });
    }, 1200);
  } catch (err) {
    stopPolling();
    activeJobId = null;
    setTailorRunning(false);
    setStatus(`Failed to start tailor job: ${err.message}`);
  }
}

async function compilePdf() {
  if (compileRunning) {
    setStatus("PDF compile is already running.");
    return;
  }

  const latex = document.getElementById("latexOutput").value;
  if (!latex.trim()) {
    setStatus("No LaTeX available to compile.");
    return;
  }

  const compileBtn = document.getElementById("compileBtn");
  compileRunning = true;
  compileBtn.disabled = true;
  compileBtn.textContent = "Compiling...";
  setStatus("Compiling PDF...");
  try {
    await api("/api/compile", {
      method: "POST",
      body: JSON.stringify({ latex }),
    });
    refreshPreview();
    setStatus("Compiled PDF and refreshed preview.");
  } catch (err) {
    setStatus(`PDF compile failed: ${err.message}`);
  } finally {
    compileRunning = false;
    compileBtn.disabled = false;
    compileBtn.textContent = "Compile to PDF";
  }
}

async function saveSessionKey() {
  const apiKey = document.getElementById("apiKeyInput").value.trim();
  const llmProvider = document.getElementById("providerSelect").value;
  if (!apiKey) {
    setStatus("Enter an API key first.");
    return;
  }

  await api("/api/session/key", {
    method: "POST",
    body: JSON.stringify({ api_key: apiKey, llm_provider: llmProvider }),
  });
  document.getElementById("apiKeyInput").value = "";
  await refreshModelsForProvider(llmProvider);
  await loadSessionKeyStatus();
  setStatus("API key saved in secure session.");
}

async function clearSessionKey() {
  await api("/api/session/key/clear", { method: "POST" });
  document.getElementById("apiKeyInput").value = "";
  setSessionKeyMeta(false);
  const llmProvider = document.getElementById("providerSelect").value;
  populateModelSelect(llmProvider);
  setStatus("Session key cleared.");
}

function bindEvents() {
  document.getElementById("saveResumeBtn").addEventListener("click", saveResume);
  document.getElementById("tailorBtn").addEventListener("click", tailorResume);
  document.getElementById("compileBtn").addEventListener("click", compilePdf);

  document.getElementById("saveInstructionsBtn").addEventListener("click", () => {
    saveInstructions().catch((err) => setStatus(err.message));
  });
  document.getElementById("resetInstructionsBtn").addEventListener("click", () => {
    resetInstructions().catch((err) => setStatus(err.message));
  });
  document.getElementById("loadBuilderBtn").addEventListener("click", loadBuilderFromRulesText);
  document.getElementById("applyBuilderBtn").addEventListener("click", applyBuilderToRulesText);
  document.getElementById("addModuleBtn").addEventListener("click", () => {
    builderState.modules.push({ key: "", rulesText: "" });
    renderBuilder();
  });
  document.getElementById("addRoleBtn").addEventListener("click", () => {
    builderState.roles.push({ key: "", name: "", mode: "json", modulesText: "", instruction: "" });
    renderBuilder();
  });
  document.getElementById("addWorkflowBtn").addEventListener("click", () => {
    builderState.workflow.push({ step: "", role: "" });
    renderBuilder();
  });

  document.getElementById("saveKeyBtn").addEventListener("click", () => {
    saveSessionKey().catch((err) => setStatus(err.message));
  });
  document.getElementById("clearKeyBtn").addEventListener("click", () => {
    clearSessionKey().catch((err) => setStatus(err.message));
  });
  document.getElementById("providerSelect").addEventListener("change", (e) => {
    refreshModelsForProvider(e.target.value).catch(() => populateModelSelect(e.target.value));
  });
  document.getElementById("resumeInput").addEventListener("input", (e) => {
    writeLocal(LOCAL_KEYS.resume, e.target.value || "");
  });
  document.getElementById("instructionsInput").addEventListener("input", (e) => {
    writeLocal(LOCAL_KEYS.instructions, e.target.value || "");
  });
}

setupTabs();
setupBuilderTabs();
bindEvents();
loadState().catch((err) => setStatus(err.message));

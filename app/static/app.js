let activeJobId = null;
let pollTimer = null;
let workflowSteps = [];

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

function parseWorkflowStepsFromText(content) {
  const match = content.match(/Workflow \(when user provides JD \+ LaTeX\)([\s\S]*)$/m);
  if (!match) {
    return [];
  }

  const lines = match[1].split("\n");
  const steps = [];
  for (const line of lines) {
    const stepMatch = line.match(/^\s*\d+\)\s*(.+)\s*$/);
    if (stepMatch) {
      steps.push(stepMatch[1]);
    }
  }
  return steps;
}

function replaceWorkflowSection(content, steps) {
  const header = "Workflow (when user provides JD + LaTeX)";
  const stepText = steps.map((s, i) => `${i + 1}) ${s}`).join("\n");
  const newSection = `${header}\n${stepText}`;

  const workflowRegex = /Workflow \(when user provides JD \+ LaTeX\)[\s\S]*$/m;
  if (workflowRegex.test(content)) {
    return content.replace(workflowRegex, newSection);
  }
  const spacer = content.endsWith("\n") ? "\n" : "\n\n";
  return `${content}${spacer}${newSection}`;
}

function renderWorkflowSteps() {
  const root = document.getElementById("stepsList");
  root.innerHTML = "";

  workflowSteps.forEach((step, idx) => {
    const item = document.createElement("div");
    item.className = "step-item";

    const header = document.createElement("div");
    header.className = "step-header";
    header.innerHTML = `<span>Step ${idx + 1}</span>`;

    const actions = document.createElement("div");
    actions.className = "step-actions";

    const upBtn = document.createElement("button");
    upBtn.textContent = "Up";
    upBtn.disabled = idx === 0;
    upBtn.addEventListener("click", () => {
      if (idx === 0) return;
      [workflowSteps[idx - 1], workflowSteps[idx]] = [workflowSteps[idx], workflowSteps[idx - 1]];
      renderWorkflowSteps();
    });

    const downBtn = document.createElement("button");
    downBtn.textContent = "Down";
    downBtn.disabled = idx === workflowSteps.length - 1;
    downBtn.addEventListener("click", () => {
      if (idx === workflowSteps.length - 1) return;
      [workflowSteps[idx + 1], workflowSteps[idx]] = [workflowSteps[idx], workflowSteps[idx + 1]];
      renderWorkflowSteps();
    });

    const delBtn = document.createElement("button");
    delBtn.textContent = "Delete";
    delBtn.addEventListener("click", () => {
      workflowSteps.splice(idx, 1);
      renderWorkflowSteps();
    });

    actions.appendChild(upBtn);
    actions.appendChild(downBtn);
    actions.appendChild(delBtn);

    header.appendChild(actions);

    const input = document.createElement("input");
    input.className = "step-input";
    input.value = step;
    input.addEventListener("input", (e) => {
      workflowSteps[idx] = e.target.value;
    });

    item.appendChild(header);
    item.appendChild(input);
    root.appendChild(item);
  });
}

function syncStepsToInstructionsText() {
  const textarea = document.getElementById("instructionsInput");
  const safeSteps = workflowSteps.map((s) => s.trim()).filter((s) => s.length > 0);
  if (safeSteps.length === 0) {
    setStatus("Add at least one workflow step before syncing.");
    return false;
  }

  textarea.value = replaceWorkflowSection(textarea.value, safeSteps);
  workflowSteps = safeSteps;
  renderWorkflowSteps();
  setStatus("Workflow steps synced into rules text.");
  return true;
}

async function loadInstructions() {
  const payload = await api("/api/instructions", { method: "GET" });
  document.getElementById("instructionsInput").value = payload.content || "";
  document.getElementById("instructionsMeta").textContent = `Source: ${payload.source} | Path: ${payload.path}`;

  workflowSteps = payload.workflow_steps && payload.workflow_steps.length
    ? payload.workflow_steps.slice()
    : parseWorkflowStepsFromText(payload.content || "");

  renderWorkflowSteps();
}

async function saveInstructions() {
  syncStepsToInstructionsText();
  const content = document.getElementById("instructionsInput").value;
  const payload = await api("/api/instructions", {
    method: "PUT",
    body: JSON.stringify({ content }),
  });

  document.getElementById("instructionsMeta").textContent = `Source: ${payload.source} | Path: ${payload.path}`;
  workflowSteps = payload.workflow_steps || workflowSteps;
  renderWorkflowSteps();
  setStatus("Custom rules saved.");
  setSourcePill(`Instructions source: ${payload.source}`);
}

async function resetInstructions() {
  const payload = await api("/api/instructions/reset", { method: "POST" });
  document.getElementById("instructionsInput").value = payload.content || "";
  document.getElementById("instructionsMeta").textContent = `Source: ${payload.source} | Path: ${payload.path}`;
  workflowSteps = payload.workflow_steps || [];
  renderWorkflowSteps();
  setStatus("Reset to default rules file.");
  setSourcePill("Instructions source: default");
}

async function loadState() {
  const state = await api("/api/state", { method: "GET" });
  document.getElementById("resumeInput").value = state.resume_latex || "";
  document.getElementById("latexOutput").value = state.resume_latex || "";

  setStatus(
    `LLM: ${state.llm_enabled ? "enabled" : "disabled"} | PDF: ${state.pdf_available ? "available" : "not compiled"}`
  );
  setSourcePill(`Instructions source: ${state.instructions_source} | ${state.instructions_path}`);

  if (state.pdf_available) {
    refreshPreview();
  }

  await loadInstructions();
}

async function saveResume() {
  const resume = document.getElementById("resumeInput").value;
  await api("/api/resume", {
    method: "PUT",
    body: JSON.stringify({ resume_latex: resume }),
  });
  document.getElementById("latexOutput").value = resume;
  setStatus("Resume cache saved.");
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollJobStatus() {
  if (!activeJobId) {
    return;
  }

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
    setStatus("Tailoring complete.");
    return;
  }

  if (job.status === "failed") {
    stopPolling();
    activeJobId = null;
    setStatus(`Tailoring failed: ${job.error || "Unknown error"}`);
  }
}

async function tailorResume() {
  const jd = document.getElementById("jdInput").value.trim();
  if (!jd) {
    setStatus("Paste a job description first.");
    return;
  }

  stopPolling();
  setProgress(0, "Queued");
  setStatus("Starting tailor job...");

  const start = await api("/api/tailor/start", {
    method: "POST",
    body: JSON.stringify({ job_description: jd }),
  });

  activeJobId = start.job_id;
  await pollJobStatus();
  pollTimer = setInterval(() => {
    pollJobStatus().catch((err) => {
      stopPolling();
      activeJobId = null;
      setStatus(`Progress polling failed: ${err.message}`);
    });
  }, 1200);
}

async function compilePdf() {
  const latex = document.getElementById("latexOutput").value;
  if (!latex.trim()) {
    setStatus("No LaTeX available to compile.");
    return;
  }

  setStatus("Compiling PDF...");
  await api("/api/compile", {
    method: "POST",
    body: JSON.stringify({ latex }),
  });
  refreshPreview();
  setStatus("Compiled PDF and refreshed preview.");
}

function addWorkflowStep() {
  workflowSteps.push("New step: describe purpose and output.");
  renderWorkflowSteps();
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
  document.getElementById("addStepBtn").addEventListener("click", addWorkflowStep);
  document.getElementById("syncStepsBtn").addEventListener("click", syncStepsToInstructionsText);
}

setupTabs();
bindEvents();
loadState().catch((err) => setStatus(err.message));

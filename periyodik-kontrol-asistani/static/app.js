const docList = document.getElementById("docList");
const fileInput = document.getElementById("fileInput");
const dropZone = document.getElementById("dropZone");
const generateBtn = document.getElementById("generateBtn");
const generateStatus = document.getElementById("generateStatus");
const tbody = document.querySelector("#suggestionsTable tbody");
const emptyState = document.getElementById("emptyState");
const skillsList = document.getElementById("skillsList");
const toastContainer = document.getElementById("toastContainer");
const llmDot = document.getElementById("llmDot");
const llmStatusText = document.getElementById("llmStatusText");
const exportWordBtn = document.getElementById("exportWordBtn");
const exportExcelBtn = document.getElementById("exportExcelBtn");
const steps = document.querySelectorAll(".step");

const FIELD_ORDER = ["kontrol_adi", "kategori", "hat", "siklik", "risk", "efor", "gerekce"];
let currentSuggestions = [];
let currentRunId = null;

// ---------- Toast ----------
function showToast(message, type = "default") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  toastContainer.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

// ---------- fetch helper ----------
async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

function setActiveStep(n) {
  steps.forEach((s) => s.classList.toggle("active", Number(s.dataset.step) <= n));
}

// ---------- health ----------
async function checkHealth() {
  try {
    const h = await fetchJSON("/api/health");
    llmDot.classList.add("ok");
    llmStatusText.textContent = `Lokal model: ${h.llm_model} (${h.llm_base_url})`;
  } catch (e) {
    llmDot.classList.add("bad");
    llmStatusText.textContent = "Sunucuya ulaşılamadı";
  }
}

// ---------- documents ----------
function docIconSvg() {
  return `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Z"/><path d="M14 2v6h6"/></svg>`;
}

async function loadDocuments() {
  const docs = await fetchJSON("/api/documents");
  docList.innerHTML = "";
  docs.forEach((d) => {
    const li = document.createElement("li");
    li.className = "doc-item";
    li.innerHTML = `
      <span class="doc-name">${docIconSvg()} ${escapeHtml(d.filename)}</span>
      <button data-id="${d.id}" class="btn btn-sm btn-ghost del-doc">Sil</button>`;
    docList.appendChild(li);
  });
  docList.querySelectorAll(".del-doc").forEach((btn) => {
    btn.onclick = async () => {
      await fetchJSON(`/api/documents/${btn.dataset.id}`, { method: "DELETE" });
      showToast("Belge silindi");
      loadDocuments();
    };
  });
  if (docs.length) setActiveStep(2);
}

// ---------- skills ----------
async function loadSkills() {
  const skills = await fetchJSON("/api/skills");
  skillsList.innerHTML = "";
  skills.forEach((s) => {
    const card = document.createElement("div");
    card.className = "skill-card";
    card.innerHTML = `
      <div class="skill-summary">
        <span>${escapeHtml(s.name)}</span>
        <svg class="chevron" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
      </div>
      <div class="skill-body">${escapeHtml(s.content)}</div>`;
    card.querySelector(".skill-summary").onclick = () => card.classList.toggle("open");
    skillsList.appendChild(card);
  });
}

function escapeHtml(str) {
  return (str || "").toString().replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function riskClass(risk) {
  if (!risk) return "";
  const norm = risk.toLowerCase().replace("ş", "s").replace("ı", "i").replace("ü", "u");
  return "pill risk-" + norm;
}

// ---------- suggestions rendering ----------
function renderSuggestions(suggestions) {
  currentSuggestions = suggestions;
  tbody.innerHTML = "";
  emptyState.style.display = suggestions.length ? "none" : "block";
  exportWordBtn.disabled = !suggestions.length;
  exportExcelBtn.disabled = !suggestions.length;
  suggestions.forEach((s, i) => {
    const row = buildRow(s);
    row.style.animationDelay = `${i * 40}ms`;
    tbody.appendChild(row);
  });
  if (suggestions.length) setActiveStep(3);
}

function buildRow(s) {
  const tr = document.createElement("tr");
  tr.dataset.id = s.id;
  tr.innerHTML = displayRowHtml(s);
  attachDisplayHandlers(tr, s);
  return tr;
}

function displayRowHtml(s) {
  return `
    <td data-field="kontrol_adi">${escapeHtml(s.kontrol_adi)}</td>
    <td data-field="kategori">${escapeHtml(s.kategori)}</td>
    <td data-field="hat"><span class="badge">${escapeHtml(s.hat) || "-"}</span></td>
    <td data-field="siklik">${escapeHtml(s.siklik)}</td>
    <td data-field="risk"><span class="${riskClass(s.risk)}">${escapeHtml(s.risk)}</span></td>
    <td data-field="efor">${escapeHtml(s.efor)}</td>
    <td data-field="gerekce">${escapeHtml(s.gerekce)}</td>
    <td class="fb-cell">
      <div class="fb-row">
        <button class="btn btn-sm btn-success" data-action="kabul">Kabul</button>
        <button class="btn btn-sm btn-danger" data-action="red">Red</button>
        <button class="btn btn-sm btn-ghost" data-action="duzenle">Düzenle</button>
      </div>
      <div class="status-note">${s.status && s.status !== "bekliyor" ? "Durum: " + escapeHtml(s.status) : ""}</div>
      <div class="prompt-row">
        <input type="text" class="prompt-input" placeholder="Bu kontrole feedback yaz (ör: ayda bir yeterli)..." />
        <button class="btn btn-sm btn-ghost" data-action="prompt">Gönder</button>
      </div>
      <div class="lesson-note"></div>
    </td>`;
}

function editRowHtml(s) {
  const inputs = FIELD_ORDER.map(
    (f) =>
      `<td data-field="${f}"><input type="text" class="edit-input" data-field="${f}" value="${escapeHtml(s[f]).replace(/"/g, "&quot;")}" /></td>`
  ).join("");
  return `
    ${inputs}
    <td class="fb-cell">
      <div class="fb-row">
        <button class="btn btn-sm btn-primary" data-action="kaydet">Kaydet</button>
        <button class="btn btn-sm btn-ghost" data-action="iptal">İptal</button>
      </div>
    </td>`;
}

function attachDisplayHandlers(tr, s) {
  tr.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.onclick = () => handleAction(tr, s, btn.dataset.action);
  });
}

async function handleAction(tr, s, action) {
  if (action === "kabul" || action === "red") {
    try {
      await fetchJSON(`/api/suggestions/${s.id}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ karar: action }),
      });
      s.status = action;
      tr.innerHTML = displayRowHtml(s);
      attachDisplayHandlers(tr, s);
      tr.classList.add(action === "kabul" ? "flash-success" : "flash-danger");
      showToast(action === "kabul" ? "Kontrol kabul edildi" : "Kontrol reddedildi", action === "kabul" ? "success" : "error");
      loadSkills();
    } catch (e) {
      showToast("Hata: " + e.message, "error");
    }
    return;
  }

  if (action === "duzenle") {
    tr.innerHTML = editRowHtml(s);
    tr.querySelectorAll("button[data-action]").forEach((btn) => {
      btn.onclick = () => handleEditAction(tr, s, btn.dataset.action);
    });
    return;
  }

  if (action === "prompt") {
    const input = tr.querySelector(".prompt-input");
    const promptText = input.value.trim();
    if (!promptText) return;
    const lessonNote = tr.querySelector(".lesson-note");
    const btn = tr.querySelector('button[data-action="prompt"]');
    btn.disabled = true;
    lessonNote.textContent = "İşleniyor...";
    try {
      const result = await fetchJSON(`/api/suggestions/${s.id}/prompt-feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptText }),
      });
      if (!result.ok) {
        lessonNote.textContent = "Hata: " + result.error;
        showToast("Geri bildirim işlenemedi", "error");
      } else {
        Object.assign(s, result.suggestion);
        tr.innerHTML = displayRowHtml(s);
        attachDisplayHandlers(tr, s);
        tr.querySelector(".lesson-note").textContent = result.applied_fields
          ? "Güncellendi + öğrenildi: " + result.lesson
          : "Öğrenildi: " + result.lesson;
        tr.classList.add("flash-success");
        showToast("Geri bildirim kaydedildi", "success");
        loadSkills();
      }
    } catch (e) {
      lessonNote.textContent = "Hata: " + e.message;
      showToast("Hata: " + e.message, "error");
    }
    if (btn) btn.disabled = false;
    input.value = "";
  }
}

async function handleEditAction(tr, s, action) {
  if (action === "iptal") {
    tr.innerHTML = displayRowHtml(s);
    attachDisplayHandlers(tr, s);
    return;
  }
  if (action === "kaydet") {
    const payload = {};
    tr.querySelectorAll(".edit-input").forEach((inp) => {
      payload[inp.dataset.field] = inp.value;
    });
    try {
      const result = await fetchJSON(`/api/suggestions/${s.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (result.changed) {
        Object.assign(s, result.suggestion);
        showToast("Değişiklikler kaydedildi", "success");
      }
      tr.innerHTML = displayRowHtml(s);
      attachDisplayHandlers(tr, s);
      tr.classList.add("flash-success");
      loadSkills();
    } catch (e) {
      showToast("Hata: " + e.message, "error");
    }
  }
}

// ---------- upload ----------
async function uploadFiles(files) {
  if (!files.length) return;
  for (const file of files) {
    const fd = new FormData();
    fd.append("file", file);
    try {
      await fetchJSON("/api/documents", { method: "POST", body: fd });
      showToast(`${file.name} yüklendi`, "success");
    } catch (e) {
      showToast("Yükleme hatası: " + e.message, "error");
    }
  }
  loadDocuments();
}

fileInput.addEventListener("change", () => {
  uploadFiles(fileInput.files);
  fileInput.value = "";
});

["dragenter", "dragover"].forEach((evt) =>
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((evt) =>
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
  })
);
dropZone.addEventListener("drop", (e) => {
  if (e.dataTransfer?.files?.length) uploadFiles(e.dataTransfer.files);
});

// ---------- generate ----------
generateBtn.onclick = async () => {
  generateBtn.disabled = true;
  generateStatus.innerHTML = `<span class="spinner"></span> Üretiliyor... (lokal LLM uç noktasına bağlanıyor)`;
  try {
    const result = await fetchJSON("/api/periyodik-kontrolleri-cikart", { method: "POST" });
    if (!result.ok) {
      generateStatus.textContent = "Hata: " + result.error;
      showToast("Öneri üretilemedi", "error");
    } else {
      currentRunId = result.run_id;
      generateStatus.textContent = `${result.suggestions.length} öneri üretildi (çalışma: ${result.run_id}).`;
      renderSuggestions(result.suggestions);
      showToast(`${result.suggestions.length} öneri üretildi`, "success");
    }
  } catch (e) {
    generateStatus.textContent = "Hata: " + e.message;
    showToast("Hata: " + e.message, "error");
  }
  generateBtn.disabled = false;
};

// ---------- export ----------
exportWordBtn.onclick = () => {
  if (!currentRunId) return;
  window.open(`/api/export/word?run_id=${currentRunId}`, "_blank");
};
exportExcelBtn.onclick = () => {
  if (!currentRunId) return;
  window.open(`/api/export/excel?run_id=${currentRunId}`, "_blank");
};

checkHealth();
loadDocuments();
loadSkills();

const docList = document.getElementById("docList");
const fileInput = document.getElementById("fileInput");
const uploadBtn = document.getElementById("uploadBtn");
const generateBtn = document.getElementById("generateBtn");
const generateStatus = document.getElementById("generateStatus");
const tbody = document.querySelector("#suggestionsTable tbody");
const skillsList = document.getElementById("skillsList");

const FIELD_ORDER = ["kontrol_adi", "kategori", "hat", "siklik", "risk", "efor", "gerekce"];
let currentSuggestions = [];

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

async function loadDocuments() {
  const docs = await fetchJSON("/api/documents");
  docList.innerHTML = "";
  docs.forEach((d) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${d.filename}</span>
      <button data-id="${d.id}" class="fb-btn del-doc">Sil</button>`;
    docList.appendChild(li);
  });
  docList.querySelectorAll(".del-doc").forEach((btn) => {
    btn.onclick = async () => {
      await fetchJSON(`/api/documents/${btn.dataset.id}`, { method: "DELETE" });
      loadDocuments();
    };
  });
}

async function loadSkills() {
  const skills = await fetchJSON("/api/skills");
  skillsList.innerHTML = "";
  skills.forEach((s) => {
    const details = document.createElement("details");
    details.innerHTML = `<summary>${s.name}</summary><pre class="skill">${escapeHtml(s.content)}</pre>`;
    skillsList.appendChild(details);
  });
}

function escapeHtml(str) {
  return (str || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function riskClass(risk) {
  if (!risk) return "";
  return "risk-" + risk.toLowerCase().replace("ş", "s").replace("ı", "i").replace("ü", "u");
}

function renderSuggestions(suggestions) {
  currentSuggestions = suggestions;
  tbody.innerHTML = "";
  suggestions.forEach((s) => tbody.appendChild(buildRow(s)));
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
    <td data-field="risk" class="${riskClass(s.risk)}">${escapeHtml(s.risk)}</td>
    <td data-field="efor">${escapeHtml(s.efor)}</td>
    <td data-field="gerekce">${escapeHtml(s.gerekce)}</td>
    <td class="fb-cell">
      <div class="fb-row">
        <button class="fb-btn" data-action="kabul">Kabul</button>
        <button class="fb-btn" data-action="red">Red</button>
        <button class="fb-btn" data-action="duzenle">Düzenle</button>
      </div>
      <div class="status-note">${s.status && s.status !== "bekliyor" ? "Durum: " + escapeHtml(s.status) : ""}</div>
      <div class="prompt-row">
        <input type="text" class="prompt-input" placeholder="Bu kontrole feedback yaz (ör: ayda bir yeterli)..." />
        <button class="fb-btn" data-action="prompt">Gönder</button>
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
        <button class="fb-btn primary" data-action="kaydet">Kaydet</button>
        <button class="fb-btn" data-action="iptal">İptal</button>
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
    await fetchJSON(`/api/suggestions/${s.id}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ karar: action }),
    });
    s.status = action;
    tr.innerHTML = displayRowHtml(s);
    attachDisplayHandlers(tr, s);
    loadSkills();
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
      } else {
        Object.assign(s, result.suggestion);
        tr.innerHTML = displayRowHtml(s);
        attachDisplayHandlers(tr, s);
        tr.querySelector(".lesson-note").textContent = result.applied_fields
          ? "Güncellendi + öğrenildi: " + result.lesson
          : "Öğrenildi: " + result.lesson;
        loadSkills();
      }
    } catch (e) {
      lessonNote.textContent = "Hata: " + e.message;
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
    const result = await fetchJSON(`/api/suggestions/${s.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (result.changed) {
      Object.assign(s, result.suggestion);
    }
    tr.innerHTML = displayRowHtml(s);
    attachDisplayHandlers(tr, s);
    loadSkills();
  }
}

uploadBtn.onclick = async () => {
  const files = fileInput.files;
  if (!files.length) return;
  uploadBtn.disabled = true;
  for (const file of files) {
    const fd = new FormData();
    fd.append("file", file);
    try {
      await fetchJSON("/api/documents", { method: "POST", body: fd });
    } catch (e) {
      alert("Yükleme hatası: " + e.message);
    }
  }
  uploadBtn.disabled = false;
  fileInput.value = "";
  loadDocuments();
};

generateBtn.onclick = async () => {
  generateBtn.disabled = true;
  generateStatus.textContent = "Üretiliyor... (lokal LLM uç noktasına bağlanıyor)";
  try {
    const result = await fetchJSON("/api/periyodik-kontrolleri-cikart", { method: "POST" });
    if (!result.ok) {
      generateStatus.textContent = "Hata: " + result.error;
    } else {
      generateStatus.textContent = `${result.suggestions.length} öneri üretildi (run ${result.run_id}).`;
      renderSuggestions(result.suggestions);
    }
  } catch (e) {
    generateStatus.textContent = "Hata: " + e.message;
  }
  generateBtn.disabled = false;
};

loadDocuments();
loadSkills();

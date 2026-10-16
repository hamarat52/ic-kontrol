const docList = document.getElementById("docList");
const fileInput = document.getElementById("fileInput");
const uploadBtn = document.getElementById("uploadBtn");
const generateBtn = document.getElementById("generateBtn");
const generateStatus = document.getElementById("generateStatus");
const tbody = document.querySelector("#suggestionsTable tbody");
const skillsList = document.getElementById("skillsList");

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
  return str.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function riskClass(risk) {
  if (!risk) return "";
  return "risk-" + risk.toLowerCase().replace("ş", "s").replace("ı", "i").replace("ü","u");
}

function renderSuggestions(suggestions) {
  tbody.innerHTML = "";
  suggestions.forEach((s) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${s.kontrol_adi || ""}</td>
      <td>${s.kategori || ""}</td>
      <td><span class="badge">${s.hat || "-"}</span></td>
      <td>${s.siklik || ""}</td>
      <td class="${riskClass(s.risk)}">${s.risk || ""}</td>
      <td>${s.efor || ""}</td>
      <td>${s.gerekce || ""}</td>
      <td>
        <button class="fb-btn" data-karar="kabul" data-id="${s.id}">Kabul</button>
        <button class="fb-btn" data-karar="red" data-id="${s.id}">Red</button>
      </td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll("button[data-karar]").forEach((btn) => {
    btn.onclick = async () => {
      btn.disabled = true;
      await fetchJSON(`/api/suggestions/${btn.dataset.id}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ karar: btn.dataset.karar }),
      });
      btn.textContent = btn.dataset.karar === "kabul" ? "Kabul edildi ✓" : "Reddedildi";
      loadSkills();
    };
  });
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

/* Periyodik Kontrol Asistanı — istemci
   Kural: hareket yalnız ton/opaklık; yer değiştiren tek şey sağ panel ve sohbet. */

const $ = (s, r = document) => r.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const KAT_ICO = { "Operasyonel": "⚙️", "Mevzuat Uyum": "⚖️", "Bilgi Sistemleri": "🛡️", "Finansal Raporlama": "📊", "AML / Şüpheli İşlem": "🔍" };
const KAT_ORDER = Object.keys(KAT_ICO);
const RISK_CLS = { "Kritik": "r-kritik", "Yüksek": "r-yuksek", "Orta": "r-orta", "Düşük": "r-dusuk" };
const HAT_ADI = { "1": "1 — Operasyonel yönetim", "2": "2 — Risk / uyum", "3": "3 — İç denetim" };

const S = {
  docs: [], sets: [], lib: [], health: null, meta: null,
  route: { name: "home" }, set: null, poll: null,
  filter: "all", q: "", selectedId: null, chatBusy: false, fresh: new Set(),
};
const isGen = (s) => s && s.durum === "uretiliyor";

/* ---------------------------------------------------------------- yardımcılar */
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = `${res.status}`;
    try { const j = await res.json(); msg = j.detail || j.error || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}
const jsonOpts = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function toDate(s) { return s ? new Date(s.replace(" ", "T") + "Z") : null; }
function fmtDate(s, time = false) {
  const d = toDate(s); if (!d) return "";
  const o = { day: "numeric", month: "short" };
  if (d.getFullYear() !== new Date().getFullYear() || !time) o.year = "numeric";
  if (time) { o.hour = "2-digit"; o.minute = "2-digit"; }
  return d.toLocaleString("tr-TR", o);
}
function fmtTime(s) { const d = toDate(s); return d ? d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }) : ""; }
function setIco(title = "") {
  const t = title.toLocaleLowerCase("tr");
  if (/kredi|tahsis|limit/.test(t)) return "🏦";
  if (/ödeme|transfer|eft|havale/.test(t)) return "💸";
  if (/erişim|yetki|kullanıcı|bilgi sistem/.test(t)) return "🔐";
  if (/finans|rapor|muhasebe/.test(t)) return "🧾";
  if (/aml|masak|aklama|şüpheli/.test(t)) return "🔍";
  return "📋";
}
let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast on" + (err ? " err" : "");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.className = "toast" + (err ? " err" : "")), 2600);
}
function download(url) { const a = document.createElement("a"); a.href = url; a.download = ""; document.body.appendChild(a); a.click(); a.remove(); }
function autosize(el) { el.style.height = "auto"; el.style.height = el.scrollHeight + "px"; }
const SVG = {
  check: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 5 5 9-10"/></svg>`,
  down: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0-4-4m4 4 4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>`,
  more: `<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/></svg>`,
  search: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>`,
  close: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>`,
};

/* ---------------------------------------------------------------- veri */
async function loadBase() {
  const [docs, sets, lib] = await Promise.all([api("/api/documents"), api("/api/sets"), api("/api/library")]);
  S.docs = docs; S.sets = sets; S.lib = lib;
  renderSidebar();
}
async function refreshSets() { S.sets = await api("/api/sets"); renderSidebar(); }
async function refreshLib() { S.lib = await api("/api/library"); renderSidebar(); }

/* ---------------------------------------------------------------- yönlendirme */
function parseRoute() {
  const h = location.hash.replace(/^#\/?/, "");
  const [name, id] = h.split("/");
  if (name === "set" && id) return { name: "set", id };
  if (["belgeler", "kutuphane", "bilgi", "setler"].includes(name)) return { name };
  return { name: "home" };
}
function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }

async function route() {
  const r = parseRoute();
  const changed = JSON.stringify(r) !== JSON.stringify(S.route);
  S.route = r;
  if (changed) { closePanel(true); closeChat(); S.filter = "all"; S.q = ""; $("#scroll").scrollTop = 0; }
  if (r.name === "home" || r.name === "setler") {
    if (S.sets.length) { location.replace("#/set/" + S.sets[0].id); return; }
  }
  if (r.name === "set") {
    if (!S.set || S.set.id !== r.id || changed) {
      try { S.set = await api("/api/sets/" + r.id); }
      catch { toast("Kontrol seti bulunamadı", true); location.replace("#/"); return; }
    }
    if (isGen(S.set)) startPoll(S.set.id);
  }
  renderSidebar();
  renderView();
}

/* ---------------------------------------------------------------- sidebar */
function renderSidebar() {
  $("#cDocs").textContent = S.docs.length || "";
  $("#cSets").textContent = S.sets.length || "";
  $("#cLib").textContent = S.lib.length || "";
  const r = S.route;
  document.querySelectorAll("#nav .nav-item").forEach((b) => {
    const n = b.dataset.route;
    b.classList.toggle("active", n === r.name || (n === "setler" && (r.name === "home")));
  });
  const list = $("#setList");
  if (!S.sets.length) { list.innerHTML = `<div class="sec-empty">Henüz set yok</div>`; return; }
  list.innerHTML = S.sets.map((s) => {
    const generating = isGen(s);
    const title = s.baslik || "Yeni kontrol seti";
    return `<button class="nav-item${r.name === "set" && r.id === s.id ? " active" : ""}" data-set="${s.id}">
      <span class="ico">${setIco(title)}</span><span class="label">${esc(title)}</span>
      ${generating ? `<span class="gen-tag">üretiliyor</span>` : `<span class="count">${s.toplam || ""}</span>`}
    </button>`;
  }).join("");
}

function renderHealth() {
  const h = S.health;
  const line = $("#modelLine");
  if (!h) { line.innerHTML = `<span class="dot bad"></span>sunucuya ulaşılamadı`; return; }
  line.innerHTML = `<span class="dot ${h.llm_ok ? "ok" : "bad"}"></span>${esc(h.llm_model)} · ${h.llm_ok ? "yerel" : "bağlantı yok"}`;
  line.title = h.llm_base_url;
}

/* ---------------------------------------------------------------- görünümler */
function setTop(crumbHtml, actionsHtml = "") { $("#crumb").innerHTML = crumbHtml; $("#actions").innerHTML = actionsHtml; }

function renderView() {
  const n = S.route.name;
  $("#ask").hidden = n !== "set";
  if (n === "belgeler") return viewDocs();
  if (n === "kutuphane") return viewLibrary();
  if (n === "bilgi") return viewKnowledge();
  if (n === "set" && S.set) return viewSet();
  return viewHome();
}

/* --- ana sayfa / boş durum */
function viewHome() {
  setTop(`<b>Kontrol Setleri</b>`);
  const hasDocs = S.docs.length > 0;
  $("#view").innerHTML = `<div class="empty">
      <div class="big">📋</div>
      <h1>Henüz kontrol seti yok</h1>
      <p>${hasDocs ? "Belgelerin hazır. Periyodik kontrolleri çıkararak ilk seti oluştur." : "Süreç ve prosedür belgelerini yükle, periyodik kontrolleri birlikte çıkaralım."}</p>
      ${hasDocs ? `<button class="btn btn-ink" data-act="generate">Periyodik kontrolleri çıkart</button>`
                : `<button class="btn btn-ink" data-act="to-docs">Belge yükle</button>`}
    </div>`;
}

/* --- belgeler */
function viewDocs() {
  setTop(`<b>Belgeler</b>`);
  const busy = S.sets.some(isGen);
  const usable = S.docs.filter((d) => !d.uyari || d.char_count > 0);
  $("#view").innerHTML = `
    <h1>Belgeler</h1>
    <p class="lead">Kontrol çıkarılacak süreç, prosedür ve politika belgelerini ekle. Yeni kontrol seti, burada listelenen tüm belgelerden üretilir; uzun belgeler bölümlere ayrılıp tek tek okunur.</p>
    <div class="drop" id="drop" tabindex="0">
      <div class="big">📄</div>
      <div><strong>Belgeleri sürükle bırak</strong> ya da seçmek için tıkla</div>
      <small>PDF · Word · TXT · Markdown</small>
    </div>
    <div class="doc-list">
      ${S.docs.map((d) => `<div class="doc-row">
          <span class="ico">${d.uyari && !d.char_count ? "⚠️" : "📄"}</span>
          <div><div class="title">${esc(d.filename)}</div>
            <div class="meta">${(d.char_count || 0).toLocaleString("tr-TR")} karakter<span class="sep">·</span>${fmtDate(d.uploaded_at, true)}</div>
            ${d.uyari ? `<div class="warn">${esc(d.uyari)}</div>` : ""}</div>
          <button class="row-action" data-act="del-doc" data-id="${d.id}">Kaldır</button>
        </div>`).join("")}
    </div>
    <div class="cta">
      <button class="btn btn-ink" data-act="generate" ${!usable.length || busy ? "disabled" : ""}>Periyodik kontrolleri çıkart</button>
      <span class="hint">${busy ? "Bir set şu an üretiliyor." : usable.length ? `${usable.length} belge kullanılacak · yerel modelde belge uzunluğuna göre dakikalar sürebilir, sayfayı kapatsan da devam eder` : "Önce metin içeren en az bir belge ekle."}</span>
    </div>`;
  const drop = $("#drop");
  drop.onclick = () => $("#fileInput").click();
  drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#fileInput").click(); } };
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => upload(e.dataTransfer.files));
}

async function upload(files) {
  if (!files || !files.length) return;
  let ok = 0;
  for (const f of files) {
    const fd = new FormData(); fd.append("file", f);
    try { await api("/api/documents", { method: "POST", body: fd }); ok++; }
    catch (e) { toast(`${f.name}: ${e.message}`, true); }
  }
  S.docs = await api("/api/documents");
  renderSidebar();
  if (S.route.name === "belgeler") viewDocs();
  if (ok) toast(ok === 1 ? "Belge eklendi" : `${ok} belge eklendi`);
}

/* --- kontrol seti */
function counts(controls) {
  const c = { all: controls.length, bekliyor: 0, kabul: 0, red: 0 };
  controls.forEach((x) => (c[x.status] = (c[x.status] || 0) + 1));
  return c;
}
function visibleControls() {
  const q = S.q.trim().toLocaleLowerCase("tr");
  return S.set.controls.filter((c) =>
    (S.filter === "all" || c.status === S.filter) &&
    (!q || `${c.kontrol_adi} ${c.gerekce} ${c.kategori}`.toLocaleLowerCase("tr").includes(q)));
}

function viewSet() {
  const s = S.set;
  const generating = isGen(s);
  const exportable = !generating && s.controls.some((c) => c.status !== "red");
  setTop(
    `Kontrol Setleri <span>/</span> <b>${esc(s.baslik || "Yeni kontrol seti")}</b>`,
    `<button class="pill-btn" data-act="export-word" ${exportable ? "" : "disabled"}>${SVG.down}Word</button>
     <button class="pill-btn" data-act="export-excel" ${exportable ? "" : "disabled"}>${SVG.down}Excel</button>
     <button class="pill-btn icon-btn" data-act="menu" title="Diğer">${SVG.more}</button>
     <div class="menu" id="menu"><button class="danger" data-act="delete-set" ${generating ? "disabled" : ""}>Seti sil</button></div>`
  );
  $("#view").innerHTML = `<div id="setHead"></div><div id="setBody"></div><div id="setGaps"></div>`;
  renderSetHead(); renderSetBody(); renderGaps(); updateAskPlaceholder();
}

function progressText(s) {
  const p = s.progress || {}, n = s.controls.length;
  if (p.asama === "ozet") return "Başlık ve özet yazılıyor…";
  if (!p.toplam) return "Belgeler hazırlanıyor…";
  const where = p.belge ? ` · ${esc(p.belge)}${p.bolum ? " — " + esc(p.bolum) : ""}` : "";
  return `Bölüm ${Math.min((p.i || 0) + 1, p.toplam)}/${p.toplam}${where}${n ? ` · ${n} kontrol` : ""}`;
}

function renderSetHead() {
  const s = S.set, el = $("#setHead"); if (!el) return;
  const generating = isGen(s);
  const n = s.controls.length;
  const belge = (s.belge_adlari || []).length;
  const ist = s.istatistik || {};
  let status = "";
  if (generating) status = `<div class="status-line"><span class="orb"></span><span class="thinking"><span>${progressText(s)}</span></span>
      <button class="pill-btn" data-act="cancel" style="height:26px;margin-left:4px">Durdur</button></div>`;
  else if (s.hata) status = `<div class="status-line${s.durum === "hata" ? " error" : ""}">${esc(s.hata)}</div>`;
  const notes = [];
  if (!generating && ist.tekrar) notes.push(`${ist.tekrar} tekrar ayıklandı`);
  if (ist.reddedilene_benzer) notes.push(`daha önce reddedilene benzeyen ${ist.reddedilene_benzer} öneri elendi`);
  if (ist.dogrulanamayan) notes.push(`${ist.dogrulanamayan} alıntı belgede bulunamadı`);
  el.innerHTML = `
    <h1>${esc(s.baslik || "Adsız kontrol seti")}</h1>
    <div class="source">
      <span>📄 ${belge} belge</span>${ist.bolum ? `<span class="sep">·</span><span>${ist.bolum} bölüm</span>` : ""}
      <span class="sep">·</span><span>${fmtDate(s.created_at)}</span>
      <span class="sep">·</span><span>${n} kontrol</span><span class="sep">·</span><span>${esc(s.model || "")}</span>
    </div>
    ${notes.length ? `<div class="notes">${notes.map(esc).join(" · ")}</div>` : ""}
    ${s.ozet ? `<p class="lead">${esc(s.ozet)}</p>` : generating ? `<p class="lead muted">Belgeler bölüm bölüm okunuyor; kontroller hazırlandıkça aşağıya eklenecek. Sayfayı kapatsan da üretim devam eder.</p>` : `<div style="height:22px"></div>`}
    ${status}`;
}

function rowHtml(c) {
  const cls = ["row", c.status === "kabul" ? "done" : "", c.status === "red" ? "rejected" : "",
    S.selectedId === c.id ? "selected" : "", S.fresh.has(c.id) ? "fresh" : ""].filter(Boolean).join(" ");
  return `<div class="${cls}" data-id="${c.id}">
    <button class="cb" data-act="toggle" title="${c.status === "kabul" ? "Kabulü geri al" : "Kabul et"}">${SVG.check}</button>
    <div><div class="title">${esc(c.kontrol_adi)}</div>
      <div class="meta">${esc(c.siklik)}<span class="sep">·</span>Hat ${esc(c.hat)}<span class="sep">·</span>Efor ${esc((c.efor || "").toLocaleLowerCase("tr"))}${c.edited ? `<span class="sep">·</span>düzenlendi` : ""}</div></div>
    <span class="risk ${RISK_CLS[c.risk] || ""}"><i></i>${esc(c.risk)}</span>
  </div>`;
}

function renderSetBody() {
  const el = $("#setBody"); if (!el) return;
  const s = S.set;
  if (!s.controls.length) { el.innerHTML = ""; return; }
  const k = counts(s.controls);
  const vis = visibleControls();
  const groups = {};
  vis.forEach((c) => (groups[c.kategori] = groups[c.kategori] || []).push(c));
  const order = [...KAT_ORDER.filter((x) => groups[x]), ...Object.keys(groups).filter((x) => !KAT_ORDER.includes(x))];
  const searchFocused = document.activeElement && document.activeElement.id === "ctrlSearch";
  const caret = searchFocused ? document.activeElement.selectionStart : null;
  el.innerHTML = `
    <div class="toolbar">
      <div class="seg">
        ${[["all", "Tümü"], ["bekliyor", "Bekleyen"], ["kabul", "Kabul"], ["red", "Red"]].map(([key, label]) =>
          `<button data-filter="${key}" class="${S.filter === key ? "on" : ""}">${label}<span>${k[key] || 0}</span></button>`).join("")}
      </div>
      <label class="mini-search">${SVG.search}<input id="ctrlSearch" placeholder="Kontrollerde ara" value="${esc(S.q)}" /></label>
    </div>
    ${order.map((cat) => `<h2 class="group"><span class="ico">${KAT_ICO[cat] || "📋"}</span>${esc(cat)} <span class="count">${groups[cat].length}</span></h2>
      ${groups[cat].map(rowHtml).join("")}`).join("")}
    ${vis.length ? "" : `<div class="empty-filter">Bu filtreye uyan kontrol yok.</div>`}`;
  if (searchFocused) { const i = $("#ctrlSearch"); i.focus(); i.setSelectionRange(caret, caret); }
  S.fresh.clear();
}

function renderGaps() {
  const el = $("#setGaps"); if (!el) return;
  const g = S.set.bosluklar || [];
  el.innerHTML = g.length ? `<div class="gaps"><h2>Tespit edilen boşluklar</h2><ul>${g.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "";
}

/* --- üretim (arka planda; yoklama ile izlenir) */
async function generate() {
  if (S.sets.some(isGen)) { toast("Bir set zaten üretiliyor"); return; }
  let s;
  try { s = await api("/api/sets", { method: "POST" }); }
  catch (e) { toast(e.message, true); return; }
  s.controls = []; s.messages = [];
  S.set = s;
  await refreshSets();
  go("#/set/" + s.id);
  startPoll(s.id);
}

function startPoll(id) {
  if (S.poll && S.poll.id === id) return;
  stopPoll();
  const known = S.set && S.set.id === id ? S.set.controls : [];
  S.poll = { id, lastId: known.length ? Math.max(...known.map((c) => c.id)) : 0, timer: null };
  pollTick();
}
function stopPoll() { if (S.poll) clearTimeout(S.poll.timer); S.poll = null; }

async function pollTick() {
  const p = S.poll; if (!p) return;
  let r;
  try { r = await api(`/api/sets/${p.id}/progress?after=${p.lastId}`); }
  catch { p.timer = setTimeout(pollTick, 3000); return; }
  if (S.poll !== p) return;
  const item = S.sets.find((x) => x.id === p.id);
  if (item) { item.baslik = r.baslik; item.durum = r.durum; item.toplam = r.toplam_kontrol; }
  const viewing = S.route.name === "set" && S.route.id === p.id && S.set && S.set.id === p.id;
  if (r.controls.length) p.lastId = Math.max(p.lastId, ...r.controls.map((c) => c.id));
  if (viewing) {
    const s = S.set;
    const have = new Set(s.controls.map((c) => c.id));
    r.controls.forEach((c) => { if (!have.has(c.id)) { s.controls.push(c); S.fresh.add(c.id); } });
    const titleChanged = s.baslik !== r.baslik;
    ["baslik", "ozet", "bosluklar", "progress", "istatistik", "durum", "hata"].forEach((k) => (s[k] = r[k]));
    renderSetHead();
    if (r.controls.length) renderSetBody();
    renderGaps();
    if (titleChanged && $("#crumb b")) $("#crumb b").textContent = s.baslik;
  }
  renderSidebar();
  if (r.durum === "uretiliyor") { p.timer = setTimeout(pollTick, 1200); return; }

  // bitti
  stopPoll();
  await refreshSets();
  if (viewing) { S.set = await api("/api/sets/" + p.id); viewSet(); }
  const n = r.toplam_kontrol;
  if (r.durum === "iptal") toast(`Üretim durduruldu · ${n} kontrol`);
  else toast(n ? `${n} kontrol hazır` : "Kontrol üretilemedi", !n);
}

/* --- kararlar ve düzenleme */
function findControl(id) { return S.set && S.set.controls.find((c) => c.id === Number(id)); }

async function decide(id, karar) {
  const c = findControl(id); if (!c) return;
  const prev = c.status; c.status = karar;          // önce arayüz
  renderSetBody(); if (S.selectedId === c.id) renderPanelFoot(c);
  try { const r = await api(`/api/controls/${id}/decision`, jsonOpts("POST", { karar })); Object.assign(c, r.control); }
  catch (e) { c.status = prev; renderSetBody(); toast(e.message, true); return; }
  if (S.selectedId === c.id) loadHistory(c.id);
  refreshLib(); updateSetCounts();
}
function updateSetCounts() {
  const it = S.sets.find((x) => x.id === S.set.id); if (!it) return;
  const k = counts(S.set.controls); it.toplam = k.all; it.kabul = k.kabul; it.red = k.red; renderSidebar();
}

async function saveFields(id, fields) {
  const c = findControl(id); if (!c) return;
  const diff = {}; Object.entries(fields).forEach(([k, v]) => { if ((c[k] ?? "") !== v) diff[k] = v; });
  if (!Object.keys(diff).length) return;
  try {
    const r = await api(`/api/controls/${id}`, jsonOpts("PATCH", diff));
    Object.assign(c, r.control);
    renderSetBody(); loadHistory(id);
    const sv = $("#saved"); if (sv) { sv.classList.add("on"); setTimeout(() => sv.classList.remove("on"), 1400); }
    if (c.status === "kabul") refreshLib();
  } catch (e) { toast(e.message, true); }
}

/* ---------------------------------------------------------------- sağ panel */
function openPanel(id) {
  const c = findControl(id); if (!c) return;
  S.selectedId = c.id;
  renderPanel(c);
  $("#win").classList.add("has-panel");
  document.querySelectorAll(".row.selected").forEach((r) => r.classList.remove("selected"));
  const row = document.querySelector(`.row[data-id="${c.id}"]`); if (row) row.classList.add("selected");
  updateAskPlaceholder();
}
function closePanel(silent) {
  S.selectedId = null;
  $("#win").classList.remove("has-panel");
  if (!silent) document.querySelectorAll(".row.selected").forEach((r) => r.classList.remove("selected"));
  updateAskPlaceholder();
}

function opts(list, val) {
  const all = list.includes(val) || !val ? list : [val, ...list];
  return all.map((o) => `<option ${o === val ? "selected" : ""}>${esc(o)}</option>`).join("");
}

function kaynakBlock(c) {
  if (!c.kaynak && !c.kaynak_belge) return "";
  const where = c.kaynak_belge ? `<div class="src">📄 ${esc(c.kaynak_belge)}${c.kaynak_bolum ? ` — ${esc(c.kaynak_bolum)}` : ""}</div>` : "";
  let quote = "";
  if (c.kaynak) {
    const v = c.kaynak_dogrulandi;
    quote = `<div class="quote${v === 0 ? " unverified" : ""}">“${esc(c.kaynak)}”</div>`
      + (v === 0 ? `<div class="verify bad">Bu alıntı belgede bulunamadı; model uydurmuş olabilir. Kaynağı kontrol et.</div>`
        : v === 1 ? `<div class="verify ok">Alıntı belgede doğrulandı</div>` : "");
  }
  return `<div class="blk"><h4>Kaynak</h4>${where}${quote}</div>`;
}

function renderPanel(c) {
  const m = S.meta || { kategoriler: KAT_ORDER, sikliklar: [], riskler: [], eforlar: [] };
  $("#panel").innerHTML = `
    <div class="panel-top"><span>Kontrol detayı<span class="saved" id="saved">· Kaydedildi</span></span>
      <button class="pill-btn icon-btn" data-act="close-panel" title="Kapat (Esc)">${SVG.close}</button></div>
    <div class="panel-body">
      <textarea class="auto p-title" data-field="kontrol_adi" rows="1">${esc(c.kontrol_adi)}</textarea>
      <dl class="fields">
        <dt>Kategori</dt><dd><select data-field="kategori">${opts(m.kategoriler, c.kategori)}</select></dd>
        <dt>Sıklık</dt><dd><select data-field="siklik">${opts(m.sikliklar, c.siklik)}</select></dd>
        <dt>Risk</dt><dd><select data-field="risk">${opts(m.riskler, c.risk)}</select></dd>
        <dt>Efor</dt><dd><select data-field="efor">${opts(m.eforlar, c.efor)}</select></dd>
        <dt>Hat</dt><dd><select data-field="hat">${["1", "2", "3"].map((h) => `<option value="${h}" ${String(c.hat) === h ? "selected" : ""}>${HAT_ADI[h]}</option>`).join("")}</select></dd>
      </dl>
      <div class="blk"><h4>Gerekçe</h4><textarea class="auto" data-field="gerekce" rows="1" placeholder="Gerekçe ekle">${esc(c.gerekce)}</textarea></div>
      ${kaynakBlock(c)}
      <div class="blk"><h4>Dayanak</h4><textarea class="auto" data-field="dayanak" rows="1" placeholder="Mevzuat / politika maddesi ekle">${esc(c.dayanak)}</textarea></div>
      <div class="blk"><h4>Geçmiş</h4><ul class="hist" id="hist"><li><time></time>Yükleniyor…</li></ul></div>
    </div>
    <div class="panel-foot" id="panelFoot"></div>`;
  $("#panel").querySelectorAll("textarea.auto").forEach(autosize);
  requestAnimationFrame(() => $("#panel").querySelectorAll("textarea.auto").forEach(autosize));
  renderPanelFoot(c);
  loadHistory(c.id);
}
function renderPanelFoot(c) {
  const f = $("#panelFoot"); if (!f) return;
  f.innerHTML = `
    <button class="btn btn-ghost" data-act="${c.status === "red" ? "undo" : "reject"}">${c.status === "red" ? "Reddi geri al" : "Reddet"}</button>
    <button class="btn btn-ink" data-act="${c.status === "kabul" ? "undo" : "accept"}">${c.status === "kabul" ? "Kabulü geri al" : "Kabul et"}</button>`;
}
async function loadHistory(id) {
  try {
    const items = await api(`/api/controls/${id}/history`);
    const el = $("#hist"); if (!el || S.selectedId !== id) return;
    el.innerHTML = items.map((h) => `<li><time>${fmtTime(h.t)}</time><span>${esc(h.text)}</span></li>`).join("");
  } catch {}
}

/* ---------------------------------------------------------------- sohbet */
function updateAskPlaceholder() {
  const c = S.selectedId && findControl(S.selectedId);
  $("#askPh").textContent = c ? `“${c.kontrol_adi}” kontrolüne geri bildirim ver…` : "Bu kontrol setine sor ya da geri bildirim ver…";
  $("#chatTitle").textContent = c ? `Odak: ${c.kontrol_adi}` : "Kontrol setiyle sohbet";
  $("#chatInput").placeholder = c ? "Bu kontrol için ne değişmeli?" : "Bir şey sor ya da geri bildirim ver…";
}
function openChat() {
  if (S.route.name !== "set" || !S.set) return;
  if (isGen(S.set)) { toast("Üretim bitince sohbet açılır"); return; }
  if (!S.set.controls.length) return;
  $("#ask").classList.add("open"); renderChat();
  setTimeout(() => $("#chatInput").focus(), 60);
}
function closeChat() { $("#ask").classList.remove("open"); }

function msgHtml(m) {
  if (m.role === "user") {
    const c = m.control_id && findControl(m.control_id);
    return `<div class="msg-user">${c ? `<span class="focus-tag">${esc(c.kontrol_adi)}</span>` : ""}${esc(m.content)}</div>`;
  }
  const changes = (m.changes || []).map((ch) => `<div class="change"><b>${esc(ch.kontrol_adi)}</b>${
    Object.entries(ch.alanlar || {}).map(([k, [a, b]]) => `<span><s>${esc(a || "—")}</s> → ${esc(b)}</span>`).join("")}</div>`).join("");
  return `<div class="msg-ai${m.error ? " err" : ""}"><span class="orb"></span><div>${esc(m.content)}${changes}${
    m.lesson ? `<div class="learned">Bilgi tabanına eklendi: “${esc(m.lesson)}”</div>` : ""}</div></div>`;
}
function renderChat() {
  const msgs = S.set ? S.set.messages : [];
  const el = $("#chat");
  el.innerHTML = (msgs.length ? msgs.map(msgHtml).join("") :
    `<div class="chat-empty">Kontrolleri doğal dille düzelt: “Şube hacmi düşük, sıklıkları azalt”, “Bu kontrol neden kritik?” gibi. Bir kontrol seçiliyse mesaj ona odaklanır. Model değişiklikleri uygular ve öğrendiğini bilgi tabanına yazar.</div>`)
    + (S.chatBusy ? `<div class="thinking"><span class="orb"></span><span>Düşünüyor…</span></div>` : "");
  el.scrollTop = el.scrollHeight;
  $("#chatSend").disabled = S.chatBusy;
}
async function sendChat() {
  const input = $("#chatInput"); const text = input.value.trim();
  if (!text || S.chatBusy || !S.set) return;
  const set = S.set, control_id = S.selectedId || null;
  set.messages.push({ role: "user", content: text, control_id });
  input.value = ""; autosize(input);
  S.chatBusy = true; renderChat();
  try {
    const r = await api(`/api/sets/${set.id}/chat`, jsonOpts("POST", { message: text, control_id }));
    if (!r.ok) set.messages.push({ role: "ai", content: r.error, error: true });
    else {
      set.messages.push(r.message);
      set.controls = r.controls;
      if (S.set === set) {
        renderSetBody();
        const c = S.selectedId && findControl(S.selectedId); if (c) renderPanel(c);
        if (set.controls.some((c) => c.status === "kabul")) refreshLib();
      }
    }
  } catch (e) { set.messages.push({ role: "ai", content: e.message, error: true }); }
  S.chatBusy = false;
  if (S.set === set) renderChat();
}

/* --- kütüphane */
async function viewLibrary() {
  setTop(`<b>Kontrol Kütüphanesi</b>`);
  const lib = S.lib;
  const q = S.q.trim().toLocaleLowerCase("tr");
  const vis = lib.filter((c) => !q || `${c.kontrol_adi} ${c.gerekce} ${c.kategori}`.toLocaleLowerCase("tr").includes(q));
  const groups = {}; vis.forEach((c) => (groups[c.kategori] = groups[c.kategori] || []).push(c));
  const order = [...KAT_ORDER.filter((x) => groups[x]), ...Object.keys(groups).filter((x) => !KAT_ORDER.includes(x))];
  const searchFocused = document.activeElement && document.activeElement.id === "ctrlSearch";
  $("#view").innerHTML = `
    <h1>Kontrol Kütüphanesi</h1>
    <div class="source"><span>📚 ${lib.length} kontrol</span><span class="sep">·</span><span>${new Set(lib.map((x) => x.set_id)).size} setten</span></div>
    <p class="lead">Kabul ettiğin kontroller burada birikir ve sonraki setlerde tekrar kullanılabilir. Bir kontrolü setin içinde düzenlersen buradaki kopyası da güncellenir.</p>
    ${lib.length ? `<div class="toolbar"><span></span><label class="mini-search">${SVG.search}<input id="ctrlSearch" placeholder="Kütüphanede ara" value="${esc(S.q)}" /></label></div>` : ""}
    ${order.map((cat) => `<h2 class="group"><span class="ico">${KAT_ICO[cat] || "📋"}</span>${esc(cat)} <span class="count">${groups[cat].length}</span></h2>
      ${groups[cat].map((c) => `<div class="row" style="cursor:default">
        <span class="ico" style="font-size:14px">✓</span>
        <div><div class="title">${esc(c.kontrol_adi)}</div>
          <div class="meta">${esc(c.siklik)}<span class="sep">·</span>Hat ${esc(c.hat)}<span class="sep">·</span>Efor ${esc((c.efor || "").toLocaleLowerCase("tr"))}${c.set_baslik ? `<span class="sep">·</span>${esc(c.set_baslik)}` : ""}</div></div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px">
          <span class="risk ${RISK_CLS[c.risk] || ""}"><i></i>${esc(c.risk)}</span>
          <button class="row-action" data-act="lib-remove" data-id="${c.id}">Çıkar</button>
        </div></div>`).join("")}`).join("")}
    ${!lib.length ? `<div class="empty" style="margin-top:8vh"><div class="big">📚</div><h1>Kütüphane boş</h1><p>Bir kontrol setinde kontrolleri kabul ettikçe burada birikecek.</p></div>`
      : !vis.length ? `<div class="empty-filter">Aramana uyan kontrol yok.</div>` : ""}`;
  if (searchFocused) { const i = $("#ctrlSearch"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
}

/* --- bilgi tabanı */
function mdLite(src) {
  const lines = esc(src).split("\n"); let out = "", inList = false, inCode = false;
  const inline = (t) => t.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
  for (const raw of lines) {
    const l = raw.trimEnd();
    if (l.startsWith("```")) { if (inList) { out += "</ul>"; inList = false; } out += inCode ? "</pre>" : "<pre>"; inCode = !inCode; continue; }
    if (inCode) { out += l + "\n"; continue; }
    if (/^\s*[-*] /.test(l)) { if (!inList) { out += "<ul>"; inList = true; } out += `<li>${inline(l.replace(/^\s*[-*] /, ""))}</li>`; continue; }
    if (inList) { out += "</ul>"; inList = false; }
    if (/^#{2,4} /.test(l)) out += `<h4>${inline(l.replace(/^#+ /, ""))}</h4>`;
    else if (l.startsWith("&gt; ")) out += `<blockquote>${inline(l.slice(5))}</blockquote>`;
    else if (/^\d+\. /.test(l)) out += `<p>${inline(l)}</p>`;
    else if (l.trim()) out += `<p>${inline(l)}</p>`;
  }
  if (inList) out += "</ul>"; if (inCode) out += "</pre>";
  return out;
}
function parseSkill(content) {
  const lines = content.split("\n");
  const title = ((lines.find((l) => l.startsWith("# ")) || "# Skill").slice(2)).replace(/^Skill:\s*/, "");
  const idx = lines.findIndex((l) => l.trim() === "## Öğrenilenler");
  const seedLines = (idx >= 0 ? lines.slice(0, idx) : lines).filter((l) => !l.startsWith("# "));
  const learned = [];
  if (idx >= 0) lines.slice(idx + 1).forEach((l) => {
    const m = l.match(/^- \[(\d{4}-\d{2}-\d{2})(?: (\d{2}:\d{2}))?\]\s*(.+)$/);
    if (m) learned.push({ date: m[1], time: m[2] || "", text: m[3] });
  });
  return { title, seed: seedLines.join("\n").trim(), learned: learned.reverse() };
}
async function viewKnowledge() {
  setTop(`<b>Bilgi Tabanı</b>`);
  $("#view").innerHTML = `<h1>Bilgi Tabanı</h1><p class="lead muted">Yükleniyor…</p>`;
  let skills = [];
  try { skills = await api("/api/skills"); } catch (e) { toast(e.message, true); }
  if (S.route.name !== "bilgi") return;
  const parsed = skills.map((s) => ({ name: s.name, ...parseSkill(s.content) }));
  const total = parsed.reduce((a, p) => a + p.learned.length, 0);
  const icon = { "genel-cerceve": "🏛️", "kontrol-metrikleri": "📐", "masak-aml": "🔍" };
  $("#view").innerHTML = `
    <h1>Bilgi Tabanı</h1>
    <div class="source"><span>💡 ${parsed.length} konu</span><span class="sep">·</span><span>${total} öğrenilen kural</span></div>
    <p class="lead">Model her kontrol setini üretirken bu bilgileri kullanır. Reddettiğin, düzelttiğin ya da sohbette açıkladığın her şey ilgili konunun altına öğrenilen kural olarak eklenir.</p>
    ${parsed.map((p) => `<section class="kb">
      <h2><span class="ico">${icon[p.name] || "📘"}</span>${esc(p.title)}</h2>
      <p class="sub">${p.learned.length ? `${p.learned.length} öğrenilen kural` : "Henüz öğrenilen kural yok"}</p>
      ${p.learned.length ? `<ul class="learn">${p.learned.map((x) => `<li><time>${esc(x.date.slice(8, 10) + "." + x.date.slice(5, 7))} ${esc(x.time)}</time><span>${esc(x.text)}</span></li>`).join("")}</ul>` : ""}
      <details class="seed"><summary>Başlangıç bilgisi</summary><div class="md">${mdLite(p.seed)}</div></details>
    </section>`).join("")}`;
}

/* ---------------------------------------------------------------- olaylar */
document.addEventListener("click", async (e) => {
  const menu = $("#menu");
  if (menu && menu.classList.contains("open") && !e.target.closest("#menu") && !e.target.closest('[data-act="menu"]')) menu.classList.remove("open");

  const nav = e.target.closest("#nav .nav-item");
  if (nav) { go(nav.dataset.route === "setler" ? "#/setler" : "#/" + nav.dataset.route); return; }
  const setBtn = e.target.closest("[data-set]");
  if (setBtn) { go("#/set/" + setBtn.dataset.set); return; }

  const f = e.target.closest("[data-filter]");
  if (f) { S.filter = f.dataset.filter; renderSetBody(); return; }

  const act = e.target.closest("[data-act]");
  const a = act && act.dataset.act;
  if (a === "toggle") {
    const row = act.closest(".row"); const c = findControl(row.dataset.id);
    decide(c.id, c.status === "kabul" ? "bekliyor" : "kabul"); return;
  }
  if (a === "accept" || a === "reject" || a === "undo") {
    decide(S.selectedId, a === "accept" ? "kabul" : a === "reject" ? "red" : "bekliyor"); return;
  }
  if (a === "close-panel") return closePanel();
  if (a === "generate") return generate();
  if (a === "cancel") {
    act.disabled = true; act.textContent = "Durduruluyor…";
    try { await api(`/api/sets/${S.set.id}/cancel`, { method: "POST" }); } catch (err) { toast(err.message, true); }
    return;
  }
  if (a === "to-docs") return go("#/belgeler");
  if (a === "del-doc") {
    try { await api("/api/documents/" + act.dataset.id, { method: "DELETE" }); S.docs = await api("/api/documents"); renderSidebar(); viewDocs(); }
    catch (err) { toast(err.message, true); }
    return;
  }
  if (a === "export-word") return download(`/api/export/word?set_id=${S.set.id}`);
  if (a === "export-excel") return download(`/api/export/excel?set_id=${S.set.id}`);
  if (a === "menu") { $("#menu").classList.toggle("open"); return; }
  if (a === "delete-set") {
    $("#menu").classList.remove("open");
    if (!confirm(`“${S.set.baslik || "Bu set"}” silinsin mi? Kütüphanedeki kabul edilmiş kontroller korunur.`)) return;
    await api("/api/sets/" + S.set.id, { method: "DELETE" });
    S.set = null; await refreshSets(); toast("Set silindi"); go("#/"); return;
  }
  if (a === "lib-remove") {
    await api("/api/library/" + act.dataset.id, { method: "DELETE" });
    await refreshLib(); viewLibrary(); return;
  }

  const row = e.target.closest("#setBody .row");
  if (row) { const id = Number(row.dataset.id); if (S.selectedId === id) closePanel(); else openPanel(id); }
});

document.addEventListener("input", (e) => {
  if (e.target.id === "ctrlSearch") { S.q = e.target.value; S.route.name === "kutuphane" ? viewLibrary() : renderSetBody(); }
  if (e.target.matches("textarea.auto") || e.target.id === "chatInput") autosize(e.target);
});

/* panel alan kaydetme */
$("#panel").addEventListener("change", (e) => {
  const el = e.target.closest("select[data-field]"); if (el && S.selectedId) saveFields(S.selectedId, { [el.dataset.field]: el.value });
});
$("#panel").addEventListener("focusout", (e) => {
  const el = e.target.closest("textarea[data-field]"); if (!el || !S.selectedId) return;
  const v = el.value.trim();
  if (el.dataset.field === "kontrol_adi" && !v) { el.value = findControl(S.selectedId).kontrol_adi; return; }
  saveFields(S.selectedId, { [el.dataset.field]: v });
});
$("#panel").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && e.target.matches('textarea[data-field="kontrol_adi"], textarea[data-field="dayanak"]')) { e.preventDefault(); e.target.blur(); }
});

$("#fileInput").addEventListener("change", (e) => { upload(e.target.files); e.target.value = ""; });
$("#secToggle").onclick = () => $("#secSets").classList.toggle("closed");
$("#newSetBtn").onclick = () => go("#/belgeler");
$("#searchBtn").onclick = () => { const i = $("#ctrlSearch"); if (i) i.focus(); else if (S.lib.length) go("#/kutuphane"); };
$("#askBar").onclick = openChat;
$("#chatClose").onclick = closeChat;
$("#chatSend").onclick = sendChat;
$("#chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } });

document.addEventListener("keydown", (e) => {
  const mod = e.metaKey || e.ctrlKey;
  if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); $("#searchBtn").click(); return; }
  if (mod && e.key.toLowerCase() === "j") { e.preventDefault(); $("#ask").classList.contains("open") ? closeChat() : openChat(); return; }
  if (e.key === "Escape") {
    const menu = $("#menu");
    if (menu && menu.classList.contains("open")) return menu.classList.remove("open");
    if ($("#ask").classList.contains("open")) return closeChat();
    if (S.selectedId) return closePanel();
  }
});

window.addEventListener("hashchange", route);

/* ---------------------------------------------------------------- başlat */
(async function init() {
  api("/api/health").then((h) => { S.health = h; renderHealth(); }).catch(() => renderHealth());
  try { S.meta = await api("/api/meta"); } catch {}
  try { await loadBase(); } catch (e) { toast("Sunucuya ulaşılamadı", true); }
  const running = S.sets.find(isGen);
  if (running) startPoll(running.id);   // sayfa yenilendiyse üretimi izlemeye devam et
  route();
})();

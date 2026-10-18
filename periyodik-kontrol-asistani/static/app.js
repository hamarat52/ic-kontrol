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
  panelMode: null, docId: null, docBack: null, multi: new Set(), anchor: null, changed: new Set(), undo: null, kbd: false,
  uploading: [], kbEdit: null, skills: null,
  learn: null, exportOpen: false, exportSeed: true, lpEdit: null,
  docTab: "sirket", showAll: new Set(), docEdit: null, scope: null, uploadAs: null, openScopeAfter: false,
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
  refreshLearn();
}
async function refreshSets() { S.sets = await api("/api/sets"); renderSidebar(); }
async function refreshLib() { S.lib = await api("/api/library"); renderSidebar(); }

/* ---------------------------------------------------------------- yönlendirme */
function parseRoute() {
  const h = location.hash.replace(/^#\/?/, "");
  const [name, id] = h.split("/");
  if (name === "set" && id) return { name: "set", id };
  if (["belgeler", "kutuphane", "bilgi", "setler", "model"].includes(name)) return { name };
  return { name: "home" };
}
function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }

async function route() {
  const r = parseRoute();
  const changed = JSON.stringify(r) !== JSON.stringify(S.route);
  S.route = r;
  if (changed) {
    S.panelMode = null; closePanel(true);
    S.filter = "all"; S.q = ""; S.exportOpen = false; S.editConn = null; S.addingConn = false; S.kbEdit = null;
    S.multi.clear(); S.changed.clear(); S.undo = null; $("#undo").hidden = true;
    $("#scroll").scrollTop = 0;
  }
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
  if (S.health) renderHealth();
  if (S.openScopeAfter && r.name === "belgeler") { S.openScopeAfter = false; openScope(); }
}

/* ---------------------------------------------------------------- sidebar */
function renderSidebar() {
  $("#cDocs").textContent = S.docs.filter((d) => !d.yerlesik).length || "";
  $("#cSets").textContent = S.sets.length || "";
  $("#cLib").textContent = S.lib.length || "";
  const r = S.route;
  document.querySelectorAll("#nav .nav-item").forEach((b) => {
    const n = b.dataset.route;
    b.classList.toggle("active", n === r.name);
  });
  const list = $("#setList");
  if (!S.sets.length) { list.innerHTML = `<div class="sec-empty">Henüz set yok · belge yükleyip başla</div>`; return; }
  list.innerHTML = S.sets.map((s) => {
    const generating = isGen(s);
    const title = s.baslik || "Yeni kontrol seti";
    return `<button class="nav-item${r.name === "set" && r.id === s.id ? " active" : ""}" data-set="${s.id}">
      <span class="ico">${s.kapsam && s.kapsam.alanlar && s.kapsam.alanlar.length ? ALAN_IKON(s.kapsam.alanlar[0]) : setIco(title)}</span><span class="label">${esc(title)}</span>
      ${generating ? `<span class="gen-tag">üretiliyor</span>` : `<span class="count">${s.toplam || ""}</span>`}
    </button>`;
  }).join("");
}

function renderHealth() {
  const h = S.health;
  const line = $("#modelLine");
  if (!h) { line.innerHTML = `<span class="dot bad"></span>sunucuya ulaşılamadı`; return; }
  line.innerHTML = `<span class="dot ${h.llm_ok ? "ok" : "bad"}"></span>${esc(h.llm_model)} · ${h.llm_ok ? (h.tur === "bulut" ? "bulut" : "yerel") : "bağlantı yok"}`;
  $("#userBtn").title = `${h.baglanti}: ${h.llm_base_url}${h.llm_error ? " — " + h.llm_error : ""} · değiştirmek için tıkla`;
  $("#userBtn").classList.toggle("active", S.route.name === "model");
}

/* ---------------------------------------------------------------- görünümler */
function setTop(crumbHtml, actionsHtml = "") { $("#crumb").innerHTML = crumbHtml; $("#actions").innerHTML = actionsHtml; }

function renderView() {
  const n = S.route.name;
  renderBottom();
  if (n === "belgeler") return viewDocs();
  if (n === "kutuphane") return viewLibrary();
  if (n === "bilgi") return viewKnowledge();
  if (n === "model") return viewModel();
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
      ${hasDocs ? `<button class="btn btn-ink" data-act="scope-open">Periyodik kontrolleri çıkart…</button>`
                : `<button class="btn btn-ink" data-act="to-docs">Belge yükle</button>`}
    </div>`;
}

/* --- belgeler: Şirket belgeleri / Mevzuat ve standartlar */
const TUR_IKON = { esas: "📘", organizasyon: "🏢", resmi: "🇹🇷", global: "🌐", lisansli: "🔒" };
const ALAN_IKON = (a) => ((S.meta && S.meta.alanlar) || []).find((x) => x.ad === a)?.ikon || "📁";
const isOpenSrc = (d) => ["resmi", "global", "lisansli"].includes(d.tur);
const SEP = '<span class="sep">·</span>';

function alanChips(d) {
  if (!d.alanlar || !d.alanlar.length) return d.tur === "organizasyon" ? "Tüm alanlar" : `<span class="alan muted">alan seçilmedi</span>`;
  return d.alanlar.map((a) => `<span class="alan">${esc(a)}</span>`).join("");
}

function classifyLine(d) {
  const all = ((S.meta && S.meta.alanlar) || []).map((x) => x.ad);
  const rest = all.filter((a) => !d.alanlar.includes(a));
  const turOpts = ["esas", "organizasyon", "lisansli"].map((t) =>
    `<option value="${t}" ${d.tur === t ? "selected" : ""}>${esc((S.meta && S.meta.turler[t]) || t)}</option>`).join("");
  return `<div class="classify" data-classify="${d.id}">
    ${d.onerildi ? `<span class="ai">✦ Önerildi</span>` : ""}
    <label>Tür <select class="sel-inline" data-doc-tur="${d.id}">${turOpts}</select></label>
    ${d.tur === "organizasyon" ? "" : `<span class="lbl">Alan</span>${d.alanlar.map((a) =>
      `<span class="alan edit">${esc(a)}<button data-act="doc-alan-del" data-id="${d.id}" data-alan="${esc(a)}" title="Kaldır">×</button></span>`).join("")}
      ${rest.length ? `<select class="sel-inline add" data-doc-alan="${d.id}"><option value="">＋ alan</option>${rest.map((a) => `<option>${esc(a)}</option>`).join("")}</select>` : ""}`}
    <button class="link" data-act="doc-confirm" data-id="${d.id}">${d.onerildi ? "Onayla" : "Bitti"}</button>
  </div>`;
}

function docRowHtml(d) {
  const open = isOpenSrc(d) && d.yerlesik;
  const meta = [];
  if (open) {
    if (d.kurum) meta.push(esc(d.kurum));
    meta.push(`${(d.bolum || 0).toLocaleString("tr-TR")} madde/bölüm`);
    meta.push(`<span class="badge-src">güncel metin · ${fmtDate(d.uploaded_at)}</span>`);
  } else {
    meta.push(d.tur === "organizasyon" ? `${(d.char_count || 0).toLocaleString("tr-TR")} karakter` : `${d.bolum || 0} bölüm`);
    meta.push(fmtDate(d.uploaded_at, true));
  }
  meta.push(d.kullanim ? `<span class="used">${d.kullanim} sette kullanıldı</span>` : "henüz kullanılmadı");
  const editing = !d.yerlesik && (d.onerildi || S.docEdit === d.id);
  return `<div class="doc-row clickable${S.panelMode === "doc" && S.docId === d.id ? " selected" : ""}" data-doc="${d.id}">
    <span class="ico">${d.uyari && !d.char_count ? "⚠️" : open ? (d.tur === "resmi" ? "🏛️" : "🌐") : "📄"}</span>
    <div><div class="title">${esc(d.filename)}</div>
      <div class="meta doc-meta-line">${editing ? "" : `<span class="chips-in">${alanChips(d)}</span>`}<span class="mi">${meta.join(SEP)}</span></div>
      ${d.uyari ? `<div class="warn">${esc(d.uyari)}</div>` : ""}
      ${d.kopya_of ? `<div class="dup">Bu belge “${esc(d.kopya_of)}” ile aynı içerikte; üretimde bir kez kullanılır. <button class="link" data-act="del-doc" data-id="${d.id}">Kaldır</button></div>` : ""}
      ${editing ? classifyLine(d) : ""}</div>
    <span class="doc-acts"><a class="row-action" href="/api/documents/${d.id}/file?indir=1" download title="İndir">İndir</a>${d.yerlesik ? "" :
      `<button class="row-action" data-act="doc-edit" data-id="${d.id}">Düzenle</button><button class="row-action" data-act="del-doc" data-id="${d.id}">Kaldır</button>`}</span>
  </div>`;
}

function docGroup(icon, title, list, note = "", limit = 0) {
  const key = title;
  const showAll = S.showAll.has(key);
  const shown = limit && !showAll ? list.slice(0, limit) : list;
  return `<div class="grp"><div class="grp-head"><h2>${icon} ${esc(title)}</h2><span class="count">${list.length}</span>${note ? `<span class="note">${note}</span>` : ""}</div>
    <div class="doc-list">${shown.map(docRowHtml).join("")}
      ${limit && list.length > limit ? `<button class="more" data-act="grp-more" data-key="${esc(key)}">${showAll ? "Daha az göster" : `+ ${list.length - limit} belge daha`}</button>` : ""}</div></div>`;
}

function viewDocs() {
  const tab = S.docTab;
  setTop(tab === "acik" ? `<b>Belgeler</b> <span>/</span> Mevzuat ve standartlar` : `<b>Belgeler</b>`);
  const busy = S.sets.some(isGen);
  const sirket = S.docs.filter((d) => !isOpenSrc(d));
  const acik = S.docs.filter(isOpenSrc);
  const esas = sirket.filter((d) => d.tur !== "organizasyon");
  const org = sirket.filter((d) => d.tur === "organizasyon");
  const usable = esas.filter((d) => d.char_count > 0 && !d.kopya_of);
  const uploading = S.uploading.map((name) => `<div class="doc-row"><span class="ico">📄</span>
      <div><div class="title">${esc(name)}</div><div class="meta">Okunuyor…</div></div><span></span></div>`).join("");
  const tabs = `<div class="seg doc-tabs">
    <button data-doc-tab="sirket" class="${tab !== "acik" ? "on" : ""}">Şirket belgeleri<span>${sirket.length}</span></button>
    <button data-doc-tab="acik" class="${tab === "acik" ? "on" : ""}">Mevzuat ve standartlar<span>${acik.length}</span></button></div>`;
  let body;
  if (tab === "acik") {
    const lis = acik.filter((d) => d.tur === "lisansli");
    const names = ((S.meta && S.meta.eklenemeyenler) || []).map((x) => x.ad.split(" (")[0].split(" — ")[0]);
    body = `
      <p class="lead">Mevzuat ve standartlar uygulamayla birlikte gelir; internet gerekmez. Model bunlardan kontrol üretmez, kontrolün dayanağını göstermek için kullanır.</p>
      ${tabs}
      ${docGroup("🇹🇷", "Resmi düzenlemeler · Türkiye", acik.filter((d) => d.tur === "resmi"), "mevzuat.gov.tr · değişiklikler işlenmiş metin", 6)}
      ${docGroup("🌐", "Global standartlar", acik.filter((d) => d.tur === "global"), "", 6)}
      ${lis.length ? docGroup("🔒", "Lisanslı standartlar", lis, "Kurumun yüklediği · yalnız bu sunucuda") + `<div class="cta"><button class="btn btn-ghost" data-act="add-standard">Standart ekle</button></div>`
        : `<div class="grp"><div class="grp-head"><h2>🔒 Lisanslı standartlar</h2><span class="count">0</span></div>
          <div class="empty-grp"><span>${esc(names.slice(0, 5).join(", "))} telifli olduğu için uygulamayla gelmez. Kurumunun kopyası varsa ekle; yalnız bu sunucuda kalır.</span>
          <button class="btn btn-ghost" data-act="add-standard">Standart ekle</button></div></div>`}`;
  } else {
    body = `
      <p class="lead">Kontroller şirketin uygulama esaslarından üretilir. Mevzuat ve standartlar uygulamayla birlikte gelir; model onları kontrolün dayanağını göstermek için kullanır.</p>
      ${tabs}
      <div class="drop" id="drop" tabindex="0" style="margin-top:14px">
        <div class="big">📄</div>
        <div><strong>Belgeleri sürükle bırak</strong> ya da seçmek için tıkla</div>
        <small>PDF · Word · Excel · TXT · Markdown — türünü ve alanını önerir, sen onaylarsın</small>
      </div>
      ${uploading ? `<div class="doc-list" style="margin-top:14px">${uploading}</div>` : ""}
      ${esas.length ? docGroup("📘", "Uygulama esasları", esas, "Kontroller bunlardan çıkar")
        : `<div class="grp"><div class="grp-head"><h2>📘 Uygulama esasları</h2><span class="count">0</span></div><div class="empty-grp">Kontrol üretmek için en az bir uygulama esası yükle.</div></div>`}
      ${org.length ? docGroup("🏢", "Organizasyon ve görevler", org, "İsteğe bağlı · kontrolün sorumlusunu ve hattını belirlemekte kullanılır")
        : `<div class="grp"><div class="grp-head"><h2>🏢 Organizasyon ve görevler</h2><span class="count">0</span><span class="note">İsteğe bağlı</span></div>
          <div class="empty-grp">Organizasyon şeması ya da görev tanımları yüklersen her kontrolün sorumlu birimi ve savunma hattı bunlara göre belirlenir.</div></div>`}
      <div class="cta">
        <button class="btn btn-ink" data-act="scope-open" ${!usable.length || busy || S.uploading.length ? "disabled" : ""}>Periyodik kontrolleri çıkart…</button>
        <span class="hint">${busy ? "Bir set şu an üretiliyor." : usable.length ? "Önce alanı ve belgeleri seçersin" : "Önce metin içeren en az bir uygulama esası ekle."}</span>
      </div>`;
  }
  $("#view").innerHTML = `<h1>Belgeler</h1>${body}`;
  const drop = $("#drop");
  if (!drop) return;
  drop.onclick = () => { S.uploadAs = null; $("#fileInput").click(); };
  drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); drop.click(); } };
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => { S.uploadAs = null; upload(e.dataTransfer.files); });
}

async function upload(files) {
  if (!files || !files.length) return;
  const list = [...files];
  const as = S.uploadAs; S.uploadAs = null;
  S.uploading.push(...list.map((f) => f.name));
  if (S.route.name === "belgeler") viewDocs();
  let ok = 0, dup = 0;
  for (const f of list) {
    const fd = new FormData(); fd.append("file", f);
    try {
      let d = await api("/api/documents", { method: "POST", body: fd });
      if (as) d = await api(`/api/documents/${d.id}`, jsonOpts("PATCH", { tur: as }));
      ok++; if (d.kopya_of) dup++;
    } catch (e) { toast(`${f.name}: ${e.message}`, true); }
    S.uploading.splice(S.uploading.indexOf(f.name), 1);
  }
  S.docs = await api("/api/documents");
  renderSidebar();
  if (S.route.name === "belgeler") viewDocs();
  if (dup) toast(`${dup} belge zaten yüklü olanla aynı içerikte`);
  else if (ok) toast(as ? "Standart eklendi" : ok === 1 ? "Belge eklendi · türünü ve alanını kontrol et" : `${ok} belge eklendi · türlerini ve alanlarını kontrol et`);
}

async function editDoc(id, body) {
  try {
    const d = await api(`/api/documents/${id}`, jsonOpts("PATCH", body));
    const i = S.docs.findIndex((x) => x.id === d.id); if (i >= 0) S.docs[i] = d;
    if (S.route.name === "belgeler") viewDocs();
    if (S.panelMode === "scope") renderScope();
  } catch (e) { toast(e.message, true); }
}

/* --- kapsam seçimi: yeni kontrol seti (sağ panel) */
const AY = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];
function scopeTitle(alanlar) {
  const now = new Date(), when = `${AY[now.getMonth()]} ${now.getFullYear()}`;
  if (!alanlar.length) return `Kontrol seti — ${when}`;
  const shortA = (a) => a.replace(" ve Veri Güvenliği", "").replace("Bilgi Sistemleri", "Bilgi Sistemleri").replace(" ve İç Sistemler", "").replace(" ve İş Sürekliliği", "").replace(" ve Finansal Raporlama", "");
  return `${shortA(alanlar[0])}${alanlar.length > 1 ? ` +${alanlar.length - 1}` : ""} — ${when}`;
}
const esasDocs = () => S.docs.filter((d) => !isOpenSrc(d) && d.tur !== "organizasyon" && d.char_count > 0 && !d.kopya_of);
const basisDocs = () => S.docs.filter(isOpenSrc);
const orgDocs = () => S.docs.filter((d) => d.tur === "organizasyon" && d.char_count > 0);
const hasAlan = (d, set) => d.alanlar.some((a) => set.has(a));

function scopeDefaults(sc) {
  sc.belgeler = new Set(esasDocs().filter((d) => sc.alanlar.size ? hasAlan(d, sc.alanlar) : false).map((d) => d.id));
  sc.dayanak = new Set(basisDocs().filter((d) => hasAlan(d, sc.alanlar)).map((d) => d.id));
  if (!sc.nameTouched) sc.baslik = scopeTitle([...sc.alanlar]);
}

function openScope() {
  if (S.sets.some(isGen)) { toast("Bir set zaten üretiliyor"); return; }
  if (S.route.name !== "belgeler") { S.openScopeAfter = true; go("#/belgeler"); return; }
  const counts = {};
  esasDocs().forEach((d) => d.alanlar.forEach((a) => (counts[a] = (counts[a] || 0) + 1)));
  const withDocs = Object.keys(counts);
  const sc = { alanlar: new Set(withDocs.length === 1 ? withDocs : []), belgeler: new Set(), dayanak: new Set(),
               org: true, baslik: "", nameTouched: false, more: false };
  scopeDefaults(sc);
  S.scope = sc;
  renderScope();
  S.selectedId = null;
  setPanelMode("scope");
}

function pickRow(d, on, kind, extra = "") {
  return `<div class="pick${on ? "" : " off"}" data-pick="${kind}" data-id="${d.id}">
    <span class="cb">${SVG.check}</span>
    <div>${esc(d.filename)}<div class="m">${extra}</div></div></div>`;
}

function renderScope() {
  const sc = S.scope; if (!sc) return;
  const alanList = (S.meta && S.meta.alanlar) || [];
  const counts = {};
  esasDocs().forEach((d) => d.alanlar.forEach((a) => (counts[a] = (counts[a] || 0) + 1)));
  const esas = esasDocs();
  const shownEsas = sc.alanlar.size ? esas.filter((d) => hasAlan(d, sc.alanlar) || !d.alanlar.length || sc.belgeler.has(d.id)) : esas;
  const basis = basisDocs();
  const primary = basis.filter((d) => hasAlan(d, sc.alanlar) || sc.dayanak.has(d.id));
  const others = basis.filter((d) => !primary.includes(d));
  const org = orgDocs();
  const selEsas = esas.filter((d) => sc.belgeler.has(d.id));
  const bolum = selEsas.reduce((a, d) => a + (d.bolum || 0), 0);
  const label = (t) => (S.meta && S.meta.turler[t]) || t;
  $("#panel").innerHTML = `<div class="scope">
    <div class="panel-top"><span>Yeni kontrol seti</span><button class="pill-btn icon-btn" data-act="close-panel" title="Kapat (Esc)">${SVG.close}</button></div>
    <div class="panel-body">
      <h3>Hangi alanda kontrol üretelim?</h3>
      <p class="sub">Yalnız seçtiğin alanın belgeleri işlenir. Birden fazla alan seçebilirsin.</p>
      <div class="step first"><div class="step-h"><span class="n">1</span>Alan</div>
        <div class="chips">${alanList.map((a) => `<button class="chip${sc.alanlar.has(a.ad) ? " on" : ""}${counts[a.ad] ? "" : " dim"}" data-act="scope-alan" data-alan="${esc(a.ad)}">${a.ikon} ${esc(a.ad)} <span class="c">${counts[a.ad] || 0}</span></button>`).join("")}</div></div>

      <div class="step"><div class="step-h"><span class="n">2</span>Kontrol üretilecek uygulama esasları<span class="r">${selEsas.length} / ${shownEsas.length}</span></div>
        ${shownEsas.length ? `<div class="picks">${shownEsas.map((d) => pickRow(d, sc.belgeler.has(d.id), "esas",
          `${d.bolum || 0} bölüm${d.alanlar.length ? " · " + esc(d.alanlar.join(", ")) : " · alan seçilmedi"}`)).join("")}</div>`
          : `<p class="role">Bu alanda uygulama esası yok.</p>`}</div>

      <div class="step"><div class="step-h"><span class="n">3</span>Dayanak olarak bakılacak kaynaklar<span class="r">${sc.dayanak.size} / ${basis.length}</span></div>
        <div class="picks">${primary.map((d) => pickRow(d, sc.dayanak.has(d.id), "dayanak", `${esc(label(d.tur))}${d.kurum ? " · " + esc(d.kurum) : ""}`)).join("")}
          ${!primary.length ? `<div class="pick-empty">${sc.alanlar.size ? "Bu alanla eşleşen kaynak yok." : "Alan seçince ilgili mevzuat ve standartlar işaretli gelir."}</div>` : ""}
          ${others.length ? (sc.more ? others.map((d) => pickRow(d, sc.dayanak.has(d.id), "dayanak", `${esc(label(d.tur))}${d.kurum ? " · " + esc(d.kurum) : ""}`)).join("")
            + `<button class="more" data-act="scope-more">Daha az göster</button>`
            : `<button class="more" data-act="scope-more">Diğer kaynaklardan ekle… (${others.length})</button>`) : ""}</div>
        <p class="role">Bunlardan kontrol üretilmez; model her kontrol için ilgili maddeyi bulup “Dayanak” olarak gösterir.</p></div>

      <div class="step"><div class="step-h"><span class="n">4</span>Şirket bağlamı</div>
        ${org.length ? `<button class="switch-row" data-act="scope-org"><div>Organizasyon ve görev tanımlarını kullan<div class="m">${org.length} belge · kontrolün sorumlu birimini ve savunma hattını belirlemek için</div></div><span class="sw${sc.org ? "" : " off"}"></span></button>`
          : `<div class="switch-row muted"><div>Organizasyon belgesi yüklenmemiş<div class="m">İsteğe bağlı · yüklersen sorumlu birim ve hat buna göre belirlenir</div></div></div>`}</div>

      <div class="step"><div class="step-h"><span class="n">5</span>Set adı</div>
        <input class="inp-name" id="scopeName" value="${esc(sc.baslik)}" maxlength="80" /></div>
    </div>
    <div class="scope-foot"><div class="sum"><b>${selEsas.length} belge · ${bolum} bölüm</b><br>${sc.dayanak.size} dayanak kaynağı${org.length && sc.org ? " · organizasyon" : ""}${S.health ? ` · ${esc(S.health.llm_model)}` : ""}</div>
      <button class="btn btn-ink" data-act="scope-go" ${selEsas.length ? "" : "disabled"}>Kontrolleri üret</button></div>
  </div>`;
}

async function scopeGo() {
  const sc = S.scope; if (!sc) return;
  const body = { belgeler: [...sc.belgeler], dayanaklar: [...sc.dayanak], organizasyon: sc.org,
                 alanlar: [...sc.alanlar], baslik: ($("#scopeName") ? $("#scopeName").value : sc.baslik).trim() };
  const btn = $('[data-act="scope-go"]'); if (btn) btn.disabled = true;
  let s;
  try { s = await api("/api/sets", jsonOpts("POST", body)); }
  catch (e) { toast(e.message, true); if (btn) btn.disabled = false; return; }
  S.scope = null;
  s.controls = []; s.messages = [];
  S.set = s;
  await refreshSets();
  go("#/set/" + s.id);
  startPoll(s.id);
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
  renderSetHead(); renderSetBody(); renderGaps(); updateAskPlaceholder(); renderBottom();
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
  const gaps = (s.bosluklar || []).length;
  const kap = s.kapsam;
  let status = "";
  if (generating) status = `<div class="status-line"><span class="orb"></span><span class="thinking"><span>${progressText(s)}</span></span>
      <button class="pill-btn" data-act="cancel" style="height:26px;margin-left:4px">Durdur</button></div>`;
  else if (s.hata) status = `<div class="status-line${s.durum === "hata" ? " error" : ""}">${esc(s.hata)}</div>`;
  const notes = [];
  if (!generating && ist.tekrar) notes.push(`${ist.tekrar} tekrar ayıklandı`);
  if (ist.reddedilene_benzer) notes.push(`daha önce reddedilene benzeyen ${ist.reddedilene_benzer} öneri elendi`);
  if (ist.dogrulanamayan) notes.push(`${ist.dogrulanamayan} alıntı belgede bulunamadı`);
  let prog = "";
  if (!generating && n) {
    const k = counts(s.controls), done = k.kabul + k.red;
    prog = `<div class="prog"><div class="bar"><i class="a" style="width:${(k.kabul / n) * 100}%"></i><i class="r" style="width:${(k.red / n) * 100}%"></i></div>
      <span><b>${done} / ${n}</b> karar verildi · ${k.kabul} kabul · ${k.red} red · ${k.bekliyor} bekliyor</span></div>`;
  }
  el.innerHTML = `
    <h1>${esc(s.baslik || "Adsız kontrol seti")}</h1>
    <div class="head-pills">
      ${kap && kap.alanlar && kap.alanlar.length ? `<div class="source">${ALAN_IKON(kap.alanlar[0])} ${esc(kap.alanlar.join(", "))}</div>` : ""}
      ${gaps && !generating ? `<button class="gap-pill" data-act="to-gaps">⚠️ ${gaps} boşluk tespit edildi ↓</button>` : ""}
    </div>
    <div class="set-meta">${[
      `📘 ${belge} uygulama esası`,
      kap && kap.dayanak && kap.dayanak.length ? `<span title="${esc((kap.dayanak_adlari || []).join("\n"))}">${kap.dayanak.length} dayanak kaynağı</span>` : "",
      `${n} kontrol`,
      fmtDate(s.created_at),
      s.model ? `<span title="Model">${esc(s.model)}</span>` : "",
    ].filter(Boolean).map((x) => `<span class="mi">${x}</span>`).join('<span class="sep">·</span>')}</div>
    ${notes.length ? `<div class="notes">${notes.map(esc).join(" · ")}</div>` : ""}
    ${s.ozet ? `<p class="lead">${esc(s.ozet)}</p>` : generating ? `<p class="lead muted">Belgeler bölüm bölüm okunuyor; kontroller hazırlandıkça aşağıya eklenecek. Sayfayı kapatsan da üretim devam eder.</p>` : `<div style="height:22px"></div>`}
    ${prog}
    ${status}`;
}

function rowHtml(c) {
  const cls = ["row", c.status === "kabul" ? "done" : "", c.status === "red" ? "rejected" : "",
    S.selectedId === c.id ? "selected" : "", S.selectedId === c.id && S.kbd ? "kbd" : "",
    S.multi.has(c.id) ? "multi" : "", S.changed.has(c.id) ? "changed" : "",
    S.fresh.has(c.id) ? "fresh" : ""].filter(Boolean).join(" ");
  const warn = c.kaynak_dogrulandi === 0 ? `<span class="sep">·</span><span class="warn-tag">⚠ kaynak doğrulanamadı</span>` : "";
  const ch = S.changed.has(c.id) ? `<span class="sep">·</span><span class="chg-tag">sohbette değişti</span>` : "";
  return `<div class="${cls}" data-id="${c.id}">
    <button class="cb" data-act="toggle" title="${c.status === "kabul" ? "Kabulü geri al" : "Kabul et"}">${SVG.check}</button>
    <div><div class="title">${esc(c.kontrol_adi)}</div>
      <div class="meta">${esc(c.siklik)}<span class="sep">·</span>Hat ${esc(c.hat)}${c.sorumlu ? `<span class="sep">·</span>${esc(c.sorumlu)}` : `<span class="sep">·</span>Efor ${esc((c.efor || "").toLocaleLowerCase("tr"))}`}${c.edited ? `<span class="sep">·</span>düzenlendi` : ""}${warn}${ch}</div></div>
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
      <label class="mini-search">${SVG.search}<input id="ctrlSearch" placeholder="Ara" value="${esc(S.q)}" /></label>
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

/* Ekranda görünen sırayla (kategori gruplarına göre) kontrol listesi */
function orderedVisible() {
  const vis = visibleControls();
  const groups = {};
  vis.forEach((c) => (groups[c.kategori] = groups[c.kategori] || []).push(c));
  const order = [...KAT_ORDER.filter((x) => groups[x]), ...Object.keys(groups).filter((x) => !KAT_ORDER.includes(x))];
  return order.flatMap((k) => groups[k]);
}
function nextPendingAfter(id) {
  const list = orderedVisible();
  const i = list.findIndex((c) => c.id === id);
  const after = [...list.slice(i + 1), ...list.slice(0, Math.max(i, 0))];
  const n = after.find((c) => c.status === "bekliyor" && c.id !== id);
  return n ? n.id : null;
}

function refreshAfterDecision() {
  renderSetBody(); renderSetHead();
  const c = S.selectedId && findControl(S.selectedId);
  if (c && S.panelMode === "detail") renderPanelFoot(c);
  refreshLib(); updateSetCounts();
}

/* karar ver; advance=true ise sıradaki bekleyen kontrole geç */
async function decide(id, karar, { advance = false, undoable = true } = {}) {
  const c = findControl(id); if (!c) return;
  const prev = c.status;
  if (prev === karar) return;
  const next = advance && karar !== "bekliyor" ? nextPendingAfter(c.id) : null;
  c.status = karar;
  if (next) openPanel(next, { keepKbd: true });
  refreshAfterDecision();
  try { const r = await api(`/api/controls/${id}/decision`, jsonOpts("POST", { karar })); Object.assign(c, r.control); }
  catch (e) { c.status = prev; refreshAfterDecision(); toast(e.message, true); return; }
  if (S.selectedId === c.id && S.panelMode === "detail") loadHistory(c.id);
  if (undoable) showUndo([{ id: c.id, prev }], `“${short(c.kontrol_adi)}” ${LABEL[karar]}`);
  if (karar === "red") { setTimeout(refreshLearn, 6000); setTimeout(refreshLearn, 20000); }
}

async function decideMany(ids, karar) {
  const items = ids.map(findControl).filter((c) => c && c.status !== karar);
  if (!items.length) { clearMulti(); return; }
  const undo = items.map((c) => ({ id: c.id, prev: c.status }));
  items.forEach((c) => (c.status = karar));
  clearMulti(); refreshAfterDecision();
  try {
    const r = await api("/api/controls/bulk-decision", jsonOpts("POST", { ids: items.map((c) => c.id), karar }));
    r.controls.forEach((x) => { const c = findControl(x.id); if (c) Object.assign(c, x); });
  } catch (e) { undo.forEach((u) => (findControl(u.id).status = u.prev)); refreshAfterDecision(); toast(e.message, true); return; }
  showUndo(undo, `${items.length} kontrol ${LABEL[karar]}`);
}

const LABEL = { kabul: "kabul edildi", red: "reddedildi", bekliyor: "beklemeye alındı" };
const short = (t) => (t.length > 46 ? t.slice(0, 44) + "…" : t);

let undoTimer;
function showUndo(items, text) {
  S.undo = items;
  const u = $("#undo");
  u.innerHTML = `<span>${esc(text)}</span><button data-act="undo-last">Geri al</button><kbd>⌘Z</kbd>`;
  u.hidden = false;
  clearTimeout(undoTimer); undoTimer = setTimeout(() => (u.hidden = true), 6000);
}
async function undoLast() {
  const items = S.undo; if (!items || !items.length) return;
  S.undo = null; $("#undo").hidden = true;
  const byPrev = {};
  items.forEach((u) => { const c = findControl(u.id); if (c) { c.status = u.prev; (byPrev[u.prev] = byPrev[u.prev] || []).push(u.id); } });
  refreshAfterDecision();
  try {
    for (const [karar, ids] of Object.entries(byPrev)) {
      const r = await api("/api/controls/bulk-decision", jsonOpts("POST", { ids, karar }));
      r.controls.forEach((x) => { const c = findControl(x.id); if (c) Object.assign(c, x); });
    }
    toast("Geri alındı");
  } catch (e) { toast(e.message, true); }
  if (S.selectedId && S.panelMode === "detail") loadHistory(S.selectedId);
}

function updateSetCounts() {
  const it = S.sets.find((x) => x.id === S.set.id); if (!it) return;
  const k = counts(S.set.controls); it.toplam = k.all; it.kabul = k.kabul; it.red = k.red; renderSidebar();
}

/* --- çoklu seçim */
function clearMulti() { S.multi.clear(); S.anchor = null; syncRows(); renderBottom(); }
function syncRows() {
  document.querySelectorAll("#setBody .row").forEach((r) => {
    const id = Number(r.dataset.id);
    r.classList.toggle("multi", S.multi.has(id));
    r.classList.toggle("selected", S.selectedId === id);
    r.classList.toggle("kbd", S.selectedId === id && S.kbd);
  });
}
function renderBottom() {
  const onSet = S.route.name === "set" && S.set && !isGen(S.set);
  const bulk = $("#bulk"), ask = $("#ask");
  if (onSet && S.multi.size) {
    bulk.innerHTML = `<b>${S.multi.size} kontrol seçili</b>
      <button data-act="bulk-accept">Kabul et<kbd>A</kbd></button>
      <button data-act="bulk-reject">Reddet<kbd>R</kbd></button>
      <button class="ghost" data-act="bulk-clear">Seçimi kaldır<kbd>Esc</kbd></button>`;
    bulk.hidden = false; ask.hidden = true;
  } else {
    bulk.hidden = true;
    ask.hidden = !(S.route.name === "set" && S.set && S.set.controls.length) || S.panelMode === "chat";
  }
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

/* ---------------------------------------------------------------- sağ panel (detay ya da sohbet) */
function setPanelMode(mode) {
  S.panelMode = mode;
  const w = $("#win");
  w.classList.toggle("has-panel", !!mode);
  w.classList.toggle("chat-open", mode === "chat");
  w.classList.toggle("doc-open", mode === "doc");
  w.classList.toggle("scope-open", mode === "scope");
  if (mode !== "scope") S.scope = null;
  if (mode !== "doc") { S.docId = null; S.docBack = null; syncDocRows(); }
  renderBottom();
}
function openPanel(id, { keepKbd = false } = {}) {
  const c = findControl(id); if (!c) return;
  if (!keepKbd) S.kbd = false;
  S.selectedId = c.id;
  if (S.panelMode === "chat") { renderChatFocus(); syncRows(); return; }
  if (S.panelMode === "doc") S.panelMode = null;   // sohbet açıkken satır seçimi odağı değiştirir
  renderPanel(c);
  setPanelMode("detail");
  syncRows();
  const row = document.querySelector(`.row[data-id="${c.id}"]`);
  if (row && S.kbd) row.scrollIntoView({ block: "nearest" });
  updateAskPlaceholder();
}
function closePanel(silent) {
  S.selectedId = null;
  setPanelMode(null);
  if (!silent) syncRows();
  updateAskPlaceholder();
}

function opts(list, val) {
  const all = list.includes(val) || !val ? list : [val, ...list];
  return all.map((o) => `<option ${o === val ? "selected" : ""}>${esc(o)}</option>`).join("");
}

function kaynakBlock(c) {
  if (!c.kaynak && !c.kaynak_belge) return "";
  const where = c.kaynak_belge ? `<div class="src"><button class="src-link" data-act="open-src" title="Belgede göster">📄 ${esc(c.kaynak_belge)}</button>${c.kaynak_bolum ? `<span class="src-sec">${esc(c.kaynak_bolum)}</span>` : ""}</div>` : "";
  let quote = "";
  // Model bazen alıntı yerine yalnız madde numarası verir ("3.4"): bunu alıntı gibi göstermeyelim.
  if (c.kaynak && /^[\d.\s,–-]{1,12}$/.test(c.kaynak.trim())) {
    quote = `<div class="ref">Madde ${esc(c.kaynak.trim())}</div>`;
  } else if (c.kaynak) {
    const v = c.kaynak_dogrulandi;
    quote = `<div class="quote${v === 0 ? " unverified" : ""}">“${esc(c.kaynak)}”</div>`
      + (v === 0 ? `<div class="verify bad">Bu alıntı belgede bulunamadı; model uydurmuş olabilir. Kaynağı kontrol et.</div>`
        : v === 1 ? `<div class="verify ok">Alıntı belgede doğrulandı</div>` : "");
  }
  return `<div class="blk"><h4>Kaynak</h4>${where}${quote}</div>`;
}

function dayanakItems(c) {
  const bag = c.dayanak_bag || [];
  if (!bag.length) return "";
  return `<div class="basis">${bag.map((b, i) => {
    const d = S.docs.find((x) => x.id === b.doc_id);
    const kind = d ? (d.tur === "resmi" ? "Resmi · TR" : d.tur === "global" ? "Global" : "Standart") : "";
    return `<button class="basis-item" data-act="open-basis" data-i="${i}">
      <div class="h">${d && d.tur === "resmi" ? "🏛️" : "🌐"} ${esc(b.doc)} — ${esc(b.label)}<span class="k">${kind}</span></div>
      ${b.alinti ? `<div class="q">${esc(b.alinti)}…</div>` : ""}</button>`;
  }).join("")}</div>`;
}

function renderPanel(c) {
  const m = S.meta || { kategoriler: KAT_ORDER, sikliklar: [], riskler: [], eforlar: [] };
  const pending = S.set.controls.filter((x) => x.status === "bekliyor").length;
  $("#panel").innerHTML = `
    <div class="panel-top"><span>Kontrol detayı${pending ? ` · ${pending} bekleyen` : ""}<span class="saved" id="saved">· Kaydedildi</span></span>
      <button class="pill-btn icon-btn" data-act="close-panel" title="Kapat (Esc)">${SVG.close}</button></div>
    <div class="panel-body">
      <textarea class="auto p-title" data-field="kontrol_adi" rows="1">${esc(c.kontrol_adi)}</textarea>
      <dl class="fields">
        <dt>Kategori</dt><dd><select data-field="kategori">${opts(m.kategoriler, c.kategori)}</select></dd>
        <dt>Sıklık</dt><dd><select data-field="siklik">${opts(m.sikliklar, c.siklik)}</select></dd>
        <dt>Risk</dt><dd><select data-field="risk">${opts(m.riskler, c.risk)}</select></dd>
        <dt>Efor</dt><dd><select data-field="efor">${opts(m.eforlar, c.efor)}</select></dd>
        <dt>Hat</dt><dd><select data-field="hat">${["1", "2", "3"].map((h) => `<option value="${h}" ${String(c.hat) === h ? "selected" : ""}>${HAT_ADI[h]}</option>`).join("")}</select></dd>
        <dt>Sorumlu</dt><dd><textarea class="auto owner" data-field="sorumlu" rows="1" placeholder="Birim ekle">${esc(c.sorumlu || "")}</textarea></dd>
      </dl>
      <div class="blk"><h4>Gerekçe</h4><textarea class="auto" data-field="gerekce" rows="1" placeholder="Gerekçe ekle">${esc(c.gerekce)}</textarea></div>
      ${kaynakBlock(c)}
      <div class="blk"><h4>Dayanak</h4>${dayanakItems(c)}<textarea class="auto${(c.dayanak_bag || []).length ? " small" : ""}" data-field="dayanak" rows="1" placeholder="Mevzuat / politika maddesi ekle">${esc(c.dayanak)}</textarea></div>
      <div class="blk"><h4>Geçmiş</h4><ul class="hist" id="hist"><li><time></time>Yükleniyor…</li></ul></div>
    </div>
    <div class="panel-foot" id="panelFoot"></div>
    <div class="next-hint">Karar verince sıradaki bekleyen kontrol açılır</div>
    <div class="keys"><span><kbd>↑</kbd><kbd>↓</kbd>gezin</span><span><kbd>A</kbd>kabul</span><span><kbd>R</kbd>red</span><span><kbd>E</kbd>düzenle</span><span><kbd>⌘Z</kbd>geri al</span></div>`;
  $("#panel").querySelectorAll("textarea.auto").forEach(autosize);
  requestAnimationFrame(() => $("#panel").querySelectorAll("textarea.auto").forEach(autosize));
  renderPanelFoot(c);
  loadHistory(c.id);
}
function renderPanelFoot(c) {
  const f = $("#panelFoot"); if (!f) return;
  f.innerHTML = `
    <button class="btn btn-ghost" data-act="${c.status === "red" ? "undo" : "reject"}">${c.status === "red" ? "Reddi geri al" : `Reddet<span class="kh">R</span>`}</button>
    <button class="btn btn-ink" data-act="${c.status === "kabul" ? "undo" : "accept"}">${c.status === "kabul" ? "Kabulü geri al" : `Kabul et<span class="kh">A</span>`}</button>`;
}

async function loadHistory(id) {
  try {
    const items = await api(`/api/controls/${id}/history`);
    const el = $("#hist"); if (!el || S.selectedId !== id) return;
    el.innerHTML = items.map((h) => `<li><time>${fmtTime(h.t)}</time><span>${esc(h.text)}</span></li>`).join("");
  } catch {}
}

/* ---------------------------------------------------------------- belge görüntüleme (sağ panel) */
async function openDoc(id, { quote = "", bolum = "", back = null, verified = null } = {}) {
  S.docId = Number(id); S.docBack = back;
  let d;
  try { d = await api(`/api/documents/${id}/text`); } catch (e) { toast(e.message, true); return; }
  if (S.docId !== Number(id)) return;
  // Alıntıyı bul: önce tamamı, olmazsa en uzun ardışık kelime dizisi (en az 4 kelime)
  const words = (quote || "").trim().split(/\s+/).filter(Boolean).map((w) => esc(w).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const tries = [];
  for (let n = words.length; n >= Math.min(4, words.length); n--)
    for (let s = 0; s + n <= words.length; s++) tries.push(new RegExp(words.slice(s, s + n).join("\\s+"), "i"));
  const escd = d.bolumler.map((b) => esc(b.text));
  let hit = null;   // [bölüm index, regex, tam mı]
  if (words.length >= 3) {
    for (const re of tries) { const i = escd.findIndex((x) => re.test(x)); if (i >= 0) { hit = [i, re, re === tries[0]]; break; } }
  }
  const fmt = (html) => html.split("\n").map((l) => (l.startsWith("# ") ? `<b class="dh">${l.slice(2)}</b>` : l)).join("\n");
  let relIdx = -1;
  if (!hit && bolum && d.bolumler.length > 1) relIdx = d.bolumler.findIndex((b) => b.bolum === bolum);
  const secs = d.bolumler.map((b, i) => {
    let body = escd[i];
    if (hit && hit[0] === i) body = body.replace(hit[1], (m) => `<mark id="docHit">${m}</mark>`);
    return `<section class="doc-sec${i === relIdx ? " rel" : ""}"><h4>${esc(b.bolum || `Bölüm ${i + 1}`)}<span>${i === relIdx ? "ilgili bölüm · " : ""}${i + 1}/${d.bolumler.length}</span></h4><div class="doc-text">${fmt(body)}</div></section>`;
  }).join("");
  const note = !quote || words.length < 3 ? "" : !hit ? (verified === 0 ? "Alıntı belgede bulunamadı; model uydurmuş olabilir." : "")
    : !hit[2] ? "Alıntı birebir bulunamadı; en yakın eşleşen kısım işaretlendi." : "";
  const backC = back && findControl(back);
  $("#panel").innerHTML = `
    <div class="panel-top">
      ${backC ? `<button class="back-btn" data-act="doc-back">← ${esc(short(backC.kontrol_adi))}</button>` : `<span>Belge</span>`}
      <button class="pill-btn icon-btn" data-act="close-panel" title="Kapat (Esc)">${SVG.close}</button></div>
    <div class="panel-body doc-view">
      <div class="p-doc-title">${esc(d.filename)}</div>
      <div class="doc-meta">${d.yerlesik ? `${esc((S.meta && S.meta.turler[d.tur]) || d.tur)}${d.kurum ? SEP + esc(d.kurum) : ""}${SEP}${d.bolumler.length} madde/bölüm${SEP}güncel metin · ${fmtDate(d.uploaded_at)}`
        : `${d.char_count.toLocaleString("tr-TR")} karakter${SEP}${d.bolumler.length} bölüm${SEP}${fmtDate(d.uploaded_at, true)}`}</div>
      <div class="doc-actions">
        <a class="pill-btn" href="/api/documents/${d.id}/file?indir=1" download>${SVG.down}İndir</a>
        ${d.inline ? `<a class="pill-btn" href="/api/documents/${d.id}/file" target="_blank" rel="noopener">${d.yerlesik ? "Kaydedilen kopyayı aç ↗" : "Orijinali aç ↗"}</a>` : ""}
        ${d.kaynak_url ? `<a class="pill-btn" href="${esc(d.kaynak_url)}" target="_blank" rel="noopener">Resmi kaynak ↗</a>` : ""}
      </div>
      ${note ? `<div class="doc-note">${note}</div>` : ""}
      ${d.uyari ? `<div class="warn">${esc(d.uyari)}</div>` : ""}
      ${secs || `<p class="lead muted">Bu belgeden metin okunamadı.</p>`}
      <p class="doc-foot">${d.yerlesik ? "Modelin dayanak ararken okuduğu metin, madde madde gösteriliyor." : "Modelin okuduğu metin, modelin gördüğü bölümlere ayrılmış hâlde gösteriliyor."}</p>
    </div>`;
  setPanelMode("doc");
  syncDocRows();
  requestAnimationFrame(() => {
    const el = $("#docHit") || $(".doc-sec.rel");
    if (el) el.scrollIntoView({ block: "center" });
  });
}
function syncDocRows() {
  document.querySelectorAll(".doc-row[data-doc]").forEach((r) =>
    r.classList.toggle("selected", S.panelMode === "doc" && Number(r.dataset.doc) === S.docId));
}
function docByName(name) { return [...S.docs].sort((a, b) => b.id - a.id).find((d) => d.filename === name); }

/* ---------------------------------------------------------------- sohbet (sağ panelde) */
function updateAskPlaceholder() {
  const c = S.selectedId && findControl(S.selectedId);
  $("#askPh").textContent = c ? `“${c.kontrol_adi}” kontrolüne geri bildirim ver…` : "Bu kontrol setine sor ya da geri bildirim ver…";
}
function openChat() {
  if (S.route.name !== "set" || !S.set) return;
  if (isGen(S.set)) { toast("Üretim bitince sohbet açılır"); return; }
  if (!S.set.controls.length) return;
  $("#panel").innerHTML = `
    <div class="cp-head"><span><b>Sohbet</b> · bu set</span>
      <button class="pill-btn icon-btn" data-act="chat-close" title="Kapat (Esc)">${SVG.close}</button></div>
    <div id="chatFocus"></div>
    <div class="chat" id="chat"></div>
    <div class="composer">
      <textarea id="chatInput" rows="1"></textarea>
      <button class="send" data-act="chat-send" id="chatSend" title="Gönder (Enter)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5m0 0-6 6m6-6 6 6"/></svg></button>
    </div>`;
  setPanelMode("chat");
  renderChatFocus(); renderChat();
  setTimeout(() => { const i = $("#chatInput"); if (i) i.focus(); }, 80);
}
function closeChat() {
  if (S.panelMode !== "chat") return;
  const c = S.selectedId && findControl(S.selectedId);
  if (c) { S.panelMode = null; openPanel(c.id); } else closePanel();
}
function renderChatFocus() {
  const el = $("#chatFocus"); if (!el) return;
  const c = S.selectedId && findControl(S.selectedId);
  el.innerHTML = c ? `<div class="focus-chip"><span>Odak: ${esc(short(c.kontrol_adi))}</span>
      <button data-act="chat-detail" title="Detayı aç">Detay</button><button data-act="chat-unfocus" title="Odağı kaldır">✕</button></div>` : "";
  const i = $("#chatInput");
  if (i) i.placeholder = c ? "Bu kontrol için ne değişmeli?" : "Bir şey sor ya da geri bildirim ver…";
}

function msgHtml(m) {
  if (m.role === "user") {
    const c = m.control_id && findControl(m.control_id);
    return `<div class="msg-user">${c ? `<span class="focus-tag">${esc(c.kontrol_adi)}</span>` : ""}${esc(m.content)}</div>`;
  }
  const FN = { kontrol_adi: "Ad", kategori: "Kategori", hat: "Hat", siklik: "Sıklık", risk: "Risk", efor: "Efor", gerekce: "Gerekçe", dayanak: "Dayanak" };
  const changes = (m.changes || []).map((ch) => `<div class="change2">
      <div class="c-title">${esc(ch.kontrol_adi)}</div>
      ${Object.entries(ch.alanlar || {}).map(([k, [a, b]]) => `<div class="c-diff">${FN[k] || k} <s>${esc(short(String(a || "—")))}</s> → <b>${esc(short(String(b)))}</b></div>`).join("")}
      ${ch.id ? `<button class="go" data-act="show-row" data-id="${ch.id}">Listede göster</button>` : ""}
    </div>`).join("");
  return `<div class="msg-ai${m.error ? " err" : ""}"><span class="orb"></span><div>${esc(m.content)}${changes}${learnCard(m)}</div></div>`;
}
function learnCard(m) {
  const list = m.learnings || (m.learning ? [m.learning] : []);
  return list.map(learnOne).join("");
}
function learnOne(l) {
  if (!l) return "";
  if (l.durum === "onayli") return `<div class="learned">💡 Öğrenilenlere eklendi: “${esc(l.metin)}”</div>`;
  if (l.durum !== "bekliyor") return `<div class="learned muted">Yalnız bu sette kaldı.</div>`;
  const ed = S.lpEdit === l.id;
  return `<div class="proposal"><div class="h">💡 Bundan sonra da uygulayayım mı?</div>
    ${ed ? `<textarea class="lp-edit" id="lpEditInput" rows="2">${esc(l.metin)}</textarea>` : `<div class="t">${esc(l.metin)}</div>`}
    <div class="a">${ed ? `<button class="y" data-act="lp-save" data-id="${l.id}">Kaydet ve ekle</button><button class="n" data-act="lp-cancel">Vazgeç</button>`
      : `<button class="y" data-act="lp-add" data-id="${l.id}">Ekle</button><button class="n" data-act="lp-edit" data-id="${l.id}">Düzenle</button><button class="n" data-act="lp-skip" data-id="${l.id}">Yalnız bu sette kalsın</button>`}</div></div>`;
}
function renderChat() {
  const el = $("#chat"); if (!el) return;
  const msgs = S.set ? S.set.messages : [];
  el.innerHTML = (msgs.length ? msgs.map(msgHtml).join("") :
    `<div class="chat-empty">Kontrolleri doğal dille düzelt: “Şube hacmi düşük, sıklıkları azalt”, “Bu kontrol neden kritik?” gibi. Listeden bir kontrol seçersen mesaj ona odaklanır. Model değişiklikleri uygular, değişen satırlar listede işaretlenir.</div>`)
    + (S.chatBusy ? `<div class="msg-ai"><span class="orb"></span><div class="thinking"><span>Düşünüyor…</span></div></div>` : "");
  el.scrollTop = el.scrollHeight;
  const b = $("#chatSend"); if (b) b.disabled = S.chatBusy;
}
async function sendChat() {
  const input = $("#chatInput"); if (!input) return;
  const text = input.value.trim();
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
      if ((r.message.learnings || []).length) refreshLearn();
      if (S.set === set) {
        S.changed = new Set((r.message.changes || []).map((c) => c.id));
        renderSetBody(); renderSetHead();
        if (set.controls.some((c) => c.status === "kabul")) refreshLib();
      }
    }
  } catch (e) { set.messages.push({ role: "ai", content: e.message, error: true }); }
  S.chatBusy = false;
  if (S.set === set) renderChat();
}
function showRow(id) {
  if (S.filter !== "all" && !visibleControls().some((c) => c.id === Number(id))) { S.filter = "all"; renderSetBody(); }
  const row = document.querySelector(`.row[data-id="${id}"]`);
  if (row) row.scrollIntoView({ block: "center", behavior: "smooth" });
}

/* --- kütüphane */
async function viewLibrary() {
  const lib = S.lib;
  setTop(`<b>Kontroller</b>`,
    `<button class="pill-btn" data-act="lib-word" ${lib.length ? "" : "disabled"}>${SVG.down}Word</button>
     <button class="pill-btn" data-act="lib-excel" ${lib.length ? "" : "disabled"}>${SVG.down}Excel</button>`);
  const q = S.q.trim().toLocaleLowerCase("tr");
  const vis = lib.filter((c) => !q || `${c.kontrol_adi} ${c.gerekce} ${c.kategori}`.toLocaleLowerCase("tr").includes(q));
  const groups = {}; vis.forEach((c) => (groups[c.kategori] = groups[c.kategori] || []).push(c));
  const order = [...KAT_ORDER.filter((x) => groups[x]), ...Object.keys(groups).filter((x) => !KAT_ORDER.includes(x))];
  const searchFocused = document.activeElement && document.activeElement.id === "ctrlSearch";
  $("#view").innerHTML = `
    <h1>Kontroller</h1>
    <div class="source"><span>📚 ${lib.length} kontrol</span><span class="sep">·</span><span>${new Set(lib.map((x) => x.set_id)).size} setten</span></div>
    <p class="lead">Kabul ettiğin kontroller burada birikir ve sonraki setlerde tekrar kullanılabilir. Bir kontrolü setin içinde düzenlersen buradaki kopyası da güncellenir.</p>
    ${lib.length ? `<div class="toolbar"><span></span><label class="mini-search">${SVG.search}<input id="ctrlSearch" placeholder="Kontrollerde ara" value="${esc(S.q)}" /></label></div>` : ""}
    ${order.map((cat) => `<h2 class="group"><span class="ico">${KAT_ICO[cat] || "📋"}</span>${esc(cat)} <span class="count">${groups[cat].length}</span></h2>
      ${groups[cat].map((c) => `<div class="row" style="cursor:default">
        <span class="ico" style="font-size:14px">✓</span>
        <div><div class="title">${esc(c.kontrol_adi)}</div>
          <div class="meta">${esc(c.siklik)}<span class="sep">·</span>Hat ${esc(c.hat)}${c.sorumlu ? `<span class="sep">·</span>${esc(c.sorumlu)}` : `<span class="sep">·</span>Efor ${esc((c.efor || "").toLocaleLowerCase("tr"))}`}${c.set_baslik ? `<span class="sep">·</span>${esc(c.set_baslik)}` : ""}</div></div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px">
          <span class="risk ${RISK_CLS[c.risk] || ""}"><i></i>${esc(c.risk)}</span>
          <button class="row-action" data-act="lib-remove" data-id="${c.id}">Çıkar</button>
        </div></div>`).join("")}`).join("")}
    ${!lib.length ? `<div class="empty" style="margin-top:8vh"><div class="big">📚</div><h1>Henüz kontrol yok</h1><p>Bir kontrol setinde kontrolleri kabul ettikçe burada birikecek.</p></div>`
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

/* --- öğrenilenler: onay bekleyenler, tercihler (USER.md), konular, dışa aktarma */
const KAYNAK_ADI = { sohbet: "Sohbetten", ret: "Ret kararlarından", duzenleme: "Düzeltmelerinden", kararlar: "Kararlarından", elle: "Elle eklendi", eski: "Önceki sürümden" };
function shortDate(s, time = true) {
  const d = toDate(s); if (!d) return "";
  const today = new Date(); const y = new Date(); y.setDate(today.getDate() - 1);
  const hm = d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return time ? `bugün ${hm}` : "bugün";
  if (d.toDateString() === y.toDateString()) return time ? `dün ${hm}` : "dün";
  return d.toLocaleDateString("tr-TR", { day: "2-digit", month: "2-digit" }) + (time ? ` ${hm}` : "");
}
async function refreshLearn() {
  try { S.learn = await api("/api/learnings"); } catch { return; }
  const n = S.learn.bekleyen.length, b = $("#cLearn");
  if (b) { b.textContent = n || ""; b.hidden = !n; b.title = n ? `${n} öğrenme onay bekliyor` : ""; }
}
const topicOpts = (sel) => (S.learn ? S.learn.tum_konular : []).map((t) =>
  `<option value="${esc(t.name)}" ${t.name === sel ? "selected" : ""}>${esc(t.baslik)}</option>`).join("");

function pendCard(p) {
  const ed = S.kbEdit && S.kbEdit.kind === "pend" && S.kbEdit.id === p.id;
  const meta = [KAYNAK_ADI[p.kaynak] || "Öneri", p.set_baslik, shortDate(p.created_at)].filter(Boolean).map(esc).join(SEP);
  return `<div class="pend" data-pend="${p.id}">
    ${ed ? `<textarea class="pend-edit" id="kbEditInput" rows="2">${esc(p.metin)}</textarea>` : `<div class="t">${esc(p.metin)}</div>`}
    <div class="m">${meta}</div>
    ${p.neden ? `<div class="why">${esc(p.neden)}</div>` : ""}
    <div class="acts"><label class="to">Konu <select class="sel-inline" data-pend-topic="${p.id}">${topicOpts(p.skill)}</select></label><span class="sp"></span>
      ${ed ? `<button class="ghost-l" data-act="kb-cancel">Vazgeç</button>` : `<button class="ghost-l" data-act="pend-edit" data-id="${p.id}">Düzenle</button><button class="ghost-l" data-act="pend-drop" data-id="${p.id}">At</button>`}
      <button class="btn btn-ink" data-act="pend-add" data-id="${p.id}">Ekle</button></div>
  </div>`;
}

async function viewKnowledge(fresh = true) {
  setTop(`<b>Öğrenilenler</b>`, `<button class="pill-btn" data-act="export-toggle">${SVG.down}Dışa aktar</button>
    <div class="pop" id="exportPop" ${S.exportOpen ? "" : "hidden"}></div>`);
  if (fresh || !S.learn) {
    if (!S.learn) $("#view").innerHTML = `<h1>Öğrenilenler</h1><p class="lead muted">Yükleniyor…</p>`;
    await refreshLearn();
    if (!S.learn) { toast("Öğrenilenler yüklenemedi", true); return; }
  }
  if (S.route.name !== "bilgi") return;
  const L = S.learn, ed = S.kbEdit;
  const rules = L.konular.reduce((a, k) => a + k.learnings.length, 0);
  const pct = Math.min(100, Math.round((L.tercih_karakter / L.tercih_sinir) * 100));
  const prefRow = (r) => (ed && ed.kind === "pref" && ed.id === r.id)
    ? `<li class="editing"><textarea id="kbEditInput" rows="1">${esc(r.metin)}</textarea>
        <div class="edit-acts"><button class="btn btn-ink" data-act="kb-save">Kaydet</button><button class="btn btn-ghost" data-act="kb-cancel">Vazgeç</button></div></li>`
    : `<li><span>${esc(r.metin)}</span><span class="acts"><button data-act="pref-edit" data-id="${r.id}">Düzenle</button><button class="del" data-act="pref-del" data-id="${r.id}">Sil</button></span></li>`;
  const ruleRow = (k, x) => {
    const time = `<time>${esc(shortDate(x.decided_at || x.created_at))}</time>`;
    if (ed && ed.kind === "rule" && ed.id === x.id) return `<li class="editing">${time}
      <textarea id="kbEditInput" rows="2">${esc(x.metin)}</textarea>
      <div class="edit-acts"><button class="btn btn-ink" data-act="kb-save">Kaydet</button><button class="btn btn-ghost" data-act="kb-cancel">Vazgeç</button></div></li>`;
    const src = [KAYNAK_ADI[x.kaynak] || "", x.set_baslik || ""].filter(Boolean).map(esc).join(" · ");
    return `<li>${time}<span>${esc(x.metin)}${src ? `<span class="src-chip">${src}</span>` : ""}</span>
      <span class="acts"><button data-act="rule-edit" data-id="${x.id}">Düzenle</button><button class="del" data-act="rule-del" data-id="${x.id}">Sil</button></span></li>`;
  };
  $("#view").innerHTML = `
    <h1>Öğrenilenler</h1>
    <div class="source"><span>💡 ${L.konular.length} konu</span>${SEP}<span>${rules} kural</span>${SEP}<span>${L.tercihler.length} tercih</span>${L.bekleyen.length ? `${SEP}<span>${L.bekleyen.length} onay bekliyor</span>` : ""}</div>
    <p class="lead">Model her kontrol setini üretirken bunları kullanır; yalnız setin alanıyla ilgili konular ve tercihlerin modele verilir. Sohbetten ve kararlarından çıkan yeni bir kural, sen onaylamadan buraya eklenmez.</p>

    ${L.bekleyen.length ? `<section class="sec2">
      <div class="sec2-h"><h2>⏳ Onay bekleyenler</h2><span class="count">${L.bekleyen.length}</span></div>
      <p class="sub">Modelin senin geri bildiriminden çıkardığı kurallar. Ekle, düzenleyip ekle ya da at.</p>
      ${L.bekleyen.map(pendCard).join("")}</section>` : ""}

    <section class="sec2">
      <div class="sec2-h"><h2>🙋 Tercihlerim</h2><span class="count">${L.tercihler.length}</span>
        <span class="r budget">${L.tercih_karakter.toLocaleString("tr-TR")} / ${L.tercih_sinir.toLocaleString("tr-TR")} karakter <span class="b"><i style="width:${pct}%"></i></span></span></div>
      <p class="sub">Çalışma tarzın: kontrol adlarının yazılışı, ayrıntı düzeyi, öncelikler. Her sette modele verilir; dışa aktarınca USER.md olur. Giriş eklenince her kullanıcıya ayrı tutulacak.</p>
      <ul class="prefs">${L.tercihler.map(prefRow).join("")}
        ${ed && ed.kind === "newpref" ? `<li class="editing"><textarea id="kbEditInput" rows="1" placeholder="ör. Gerekçe en fazla iki cümle olsun."></textarea>
          <div class="edit-acts"><button class="btn btn-ink" data-act="kb-save">Ekle</button><button class="btn btn-ghost" data-act="kb-cancel">Vazgeç</button></div></li>` : ""}</ul>
      ${ed && ed.kind === "newpref" ? "" : `<button class="add-row" data-act="pref-new">＋ Tercih ekle</button>`}
    </section>

    ${L.konular.map((k) => `<section class="kb">
      <h2><span class="ico">${esc(k.ikon)}</span>${esc(k.baslik)}</h2>
      <p class="sub"><span class="topic-when">Kullanıldığı yer ${k.alanlar.length ? k.alanlar.map((a) => `<span class="alan">${esc(a)}</span>`).join("") : `<span class="alan">Tüm alanlar</span>`}</span>${SEP}<span>${k.kullanim_30 ? `son 30 günde ${k.kullanim_30} sette kullanıldı` : "son 30 günde kullanılmadı"}</span></p>
      ${k.learnings.length ? `<ul class="learn">${[...k.learnings].reverse().map((x) => ruleRow(k, x)).join("")}</ul>` : `<ul class="learn"><li class="none">Henüz onaylanmış kural yok.</li></ul>`}
      ${k.seed ? `<details class="seed"><summary>Başlangıç bilgisi</summary><div class="md">${mdLite(k.seed)}</div></details>` : ""}
    </section>`).join("")}`;
  if (S.exportOpen) renderExport();
  const inp = $("#kbEditInput");
  if (inp) { autosize(inp); inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
}

function renderExport() {
  const el = $("#exportPop"); if (!el || !S.learn) return;
  const withSeed = S.exportSeed !== false;
  const names = S.learn.konular.filter((k) => k.learnings.length || (withSeed && k.seed)).map((k) => k.name);
  el.innerHTML = `<h4>Öğrenilenleri dışa aktar</h4>
    <p>Hermes ve agentskills.io standardında; başka bir agent'a ya da Hermes'e olduğu gibi konabilir.</p>
    <div class="tree">ic-kontrol-ogrenilenler-${new Date().toISOString().slice(0, 10)}.zip<br>
      ${names.map((n) => `├─ ${esc(n)}/SKILL.md`).join("<br>")}<br>├─ USER.md <span>— tercihlerim</span><br>└─ BENIOKU.md <span>— nasıl kullanılır</span></div>
    <button class="ck" data-act="export-seed"><i class="${withSeed ? "" : "off"}">✓</i>Başlangıç bilgisini de ekle</button>
    <button class="btn btn-ink" data-act="export-go">İndir (.zip)</button>
    <div class="hint2">Hermes'te kullanmak için: zip'i aç, konu klasörlerini <b>~/.hermes/skills/</b> altına, USER.md içeriğini kullanıcı profiline koy.</div>`;
  el.hidden = false;
}

async function kbSave() {
  const ed = S.kbEdit, inp = $("#kbEditInput"); if (!ed || !inp) return;
  const metin = inp.value.trim();
  try {
    if (ed.kind === "rule") { if (metin) await api(`/api/learnings/${ed.id}`, jsonOpts("PATCH", { metin })); }
    else if (ed.kind === "pref") { if (metin) await api(`/api/prefs/${ed.id}`, jsonOpts("PATCH", { metin })); }
    else if (ed.kind === "newpref") { if (metin) await api("/api/prefs", jsonOpts("POST", { metin })); }
    else if (ed.kind === "pend") return decideLearning(ed.id, "onayla", { metin });
  } catch (e) { toast(e.message, true); return; }
  S.kbEdit = null; viewKnowledge();
}

/* Öneriyi onayla / at — hem Öğrenilenler sayfasından hem sohbetten */
async function decideLearning(id, karar, { metin = null, skill = null } = {}) {
  const body = { karar };
  if (metin) body.metin = metin;
  if (skill) body.skill = skill;
  let r;
  try { r = await api(`/api/learnings/${id}/decision`, jsonOpts("POST", body)); } catch (e) { toast(e.message, true); return; }
  S.kbEdit = null; S.lpEdit = null;
  if (S.set) S.set.messages.forEach((m) => {
    (m.learnings || []).forEach((x, i) => { if (x.id === id) m.learnings[i] = r.learning; });
    if (m.learning && m.learning.id === id) m.learning = r.learning;
  });
  toast(karar === "onayla" ? "💡 Öğrenilenlere eklendi" : "Öneri atıldı");
  await refreshLearn();
  if (S.route.name === "bilgi") viewKnowledge(false);
  if (S.panelMode === "chat") renderChat();
}

/* --- model ayarları */
const TUR_ADI = { yerel: "Yerel", bulut: "Bulut" };

async function viewModel(fresh = true) {
  setTop(`<b>Model</b>`);
  if (fresh || !S.models) {
    if (!S.models) $("#view").innerHTML = `<h1>Model</h1><p class="lead muted">Bağlantılar kontrol ediliyor…</p>`;
    try { S.models = await api("/api/models"); } catch (e) { toast(e.message, true); return; }
  }
  if (S.route.name !== "model") return;
  const m = S.models, a = m.aktif;
  const activeConn = m.baglantilar.find((b) => b.id === a.baglanti);
  $("#view").innerHTML = `
    <h1>Model</h1>
    <div class="source"><span>${activeConn && activeConn.tur === "bulut" ? "☁️" : "💻"} ${esc(activeConn ? activeConn.ad : "")}</span><span class="sep">·</span><span>${esc(a.model)}</span></div>
    <p class="lead">Kontrol üretimi ve sohbet seçili modelle yapılır. Kurum içinde yerel bir model sunucusunun (Ollama, LM Studio, vLLM) adresini eklemen yeterli; internet gerekmez.</p>
    ${m.baglantilar.map((b) => connBlock(b, a)).join("")}
    <div id="addConn">${S.addingConn ? connForm() : `<button class="btn btn-ghost" data-act="conn-add">Bağlantı ekle</button>`}</div>`;
}

function connBlock(b, a) {
  const status = b.tur === "bulut" && !b.anahtar_var
    ? `<span class="conn-st">anahtar bekleniyor</span>`
    : b.hata
    ? `<span class="conn-st bad">${esc(b.hata)}</span>`
    : `<span class="conn-st ok"><span class="dot ok"></span>${b.modeller.length} model</span>`;
  const editing = S.editConn === b.id;
  const needsKey = b.tur === "bulut" && !b.anahtar_var;
  const models = b.modeller.length ? b.modeller : (b.id === a.baglanti ? [a.model] : []);
  return `<section class="conn${b.id === a.baglanti ? " in-use" : ""}">
    <div class="conn-head">
      <span class="ico">${b.tur === "bulut" ? "☁️" : "💻"}</span>
      <div class="conn-title"><b>${esc(b.ad)}</b><span class="tag">${TUR_ADI[b.tur] || "Yerel"}</span>${status}
        <div class="conn-url">${esc(b.base_url)}${b.anahtar_var ? `<span class="sep">·</span>anahtar kayıtlı` : ""}</div></div>
      <button class="row-action show" data-act="conn-edit" data-id="${b.id}">${editing ? "Vazgeç" : "Düzenle"}</button>
    </div>
    ${b.tur === "bulut" ? `<p class="conn-note">Bulut modelinde belge metni internet üzerinden bu servise gönderilir. Gerçek kurum belgeleriyle yalnız izin varsa kullan.</p>` : ""}
    ${editing ? connForm(b) : needsKey ? keyForm(b) : ""}
    ${models.length ? `<div class="model-list">${models.map((name) => {
      const on = b.id === a.baglanti && name === a.model;
      return `<button class="model-row${on ? " on" : ""}" data-act="model-pick" data-conn="${b.id}" data-model="${esc(name)}">
        <span class="radio"></span><span>${esc(name)}</span>${on ? `<span class="in-use-tag">kullanılıyor</span>` : ""}</button>`;
    }).join("")}</div>` : ""}
    ${!b.modeller.length && !needsKey && !editing ? `<div class="manual">
        <input class="inp" placeholder="Model adını elle yaz (ör. llama3.1:70b)" data-manual="${b.id}">
        <button class="btn btn-ghost" data-act="model-manual" data-conn="${b.id}">Kullan</button></div>` : ""}
  </section>`;
}

function keyForm(b) {
  return `<form class="conn-form" data-conn-form="${b.id}" autocomplete="off">
    <input class="inp" name="api_key" type="password" placeholder="API anahtarı" autocomplete="new-password">
    <button class="btn btn-ink" type="submit">Kaydet</button>
  </form>`;
}

function connForm(b) {
  const isNew = !b;
  return `<form class="conn-form grid" data-conn-form="${isNew ? "" : b.id}" autocomplete="off">
    <label>Ad<input class="inp" name="ad" value="${esc(b ? b.ad : "")}" placeholder="Kurum model sunucusu"></label>
    <label>Adres<input class="inp" name="base_url" value="${esc(b ? b.base_url : "")}" placeholder="http://sunucu:11434/v1"></label>
    <label>Tür<select class="inp" name="tur">
      <option value="yerel" ${!b || b.tur !== "bulut" ? "selected" : ""}>Yerel / kurum içi</option>
      <option value="bulut" ${b && b.tur === "bulut" ? "selected" : ""}>Bulut</option></select></label>
    <label>API anahtarı<input class="inp" name="api_key" type="password" autocomplete="new-password" placeholder="${b && b.anahtar_var ? "Kayıtlı · değiştirmek için yaz" : "Gerekmiyorsa boş bırak"}"></label>
    <div class="conn-form-actions">
      <button class="btn btn-ink" type="submit">${isNew ? "Ekle" : "Kaydet"}</button>
      ${isNew ? `<button class="btn btn-ghost" type="button" data-act="conn-add-cancel">Vazgeç</button>` : ""}
      ${b && b.anahtar_var ? `<button class="btn btn-ghost" type="button" data-act="conn-key-del" data-id="${b.id}">Anahtarı sil</button>` : ""}
      ${b && b.id !== "yerel" && b.id !== S.models.aktif.baglanti ? `<button class="btn btn-ghost danger" type="button" data-act="conn-del" data-id="${b.id}">Bağlantıyı sil</button>` : ""}
    </div>
  </form>`;
}

async function pickModel(conn, model) {
  try {
    await api("/api/models/active", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ baglanti: conn, model }) });
    S.models.aktif = { baglanti: conn, model };
    viewModel(false);
    toast(`Model: ${model}`);
    api("/api/health").then((h) => { S.health = h; renderHealth(); });
  } catch (e) { toast(e.message, true); }
}

async function saveConn(form) {
  const fd = new FormData(form);
  const body = { id: form.dataset.connForm || null };
  for (const [k, v] of fd.entries()) if (String(v).trim()) body[k] = String(v).trim();
  const btn = form.querySelector('[type="submit"]'); btn.disabled = true; btn.textContent = "Bağlanıyor…";
  try {
    const r = await api("/api/models/connections", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    S.models = r; S.editConn = null; S.addingConn = false;
    const c = r.baglantilar.find((x) => x.id === r.id);
    toast(c && c.hata ? `Kaydedildi · ${c.hata}` : "Bağlantı kaydedildi", !!(c && c.hata));
    viewModel(false);
  } catch (e) { toast(e.message, true); btn.disabled = false; btn.textContent = "Kaydet"; }
}

/* ---------------------------------------------------------------- olaylar */
const typing = (el) => el && (el.matches("input, textarea, select") || el.isContentEditable);

document.addEventListener("mousedown", (e) => {
  if (e.shiftKey && e.target.closest("#setBody .row")) e.preventDefault();   // shift+tık metin seçmesin
});

document.addEventListener("click", async (e) => {
  const menu = $("#menu");
  if (menu && menu.classList.contains("open") && !e.target.closest("#menu") && !e.target.closest('[data-act="menu"]')) menu.classList.remove("open");
  if (S.exportOpen && !e.target.closest("#exportPop") && !e.target.closest('[data-act="export-toggle"]')) { S.exportOpen = false; const pp = $("#exportPop"); if (pp) pp.hidden = true; }

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
  if (a === "accept" || a === "reject") return decide(S.selectedId, a === "accept" ? "kabul" : "red", { advance: true });
  if (a === "undo") return decide(S.selectedId, "bekliyor");
  if (a === "undo-last") return undoLast();
  if (a === "bulk-accept") return decideMany([...S.multi], "kabul");
  if (a === "bulk-reject") return decideMany([...S.multi], "red");
  if (a === "bulk-clear") return clearMulti();
  if (a === "to-gaps") { const g = $("#setGaps"); if (g) g.scrollIntoView({ block: "start", behavior: "smooth" }); return; }
  if (a === "close-panel") return closePanel();
  if (a === "chat-close") return closeChat();
  if (a === "chat-send") return sendChat();
  if (a === "chat-detail") { const id = S.selectedId; S.panelMode = null; return openPanel(id); }
  if (a === "chat-unfocus") { S.selectedId = null; syncRows(); renderChatFocus(); updateAskPlaceholder(); return; }
  if (a === "show-row") return showRow(act.dataset.id);
  if (a === "open-src") {
    const c = findControl(S.selectedId); const d = c && docByName(c.kaynak_belge);
    if (!d) { toast("Belge artık yüklü değil", true); return; }
    return openDoc(d.id, { quote: c.kaynak, bolum: c.kaynak_bolum, back: c.id, verified: c.kaynak_dogrulandi });
  }
  if (a === "doc-back") { const id = S.docBack; S.panelMode = null; return openPanel(id); }
  if (a === "kb-cancel") { S.kbEdit = null; return viewKnowledge(false); }
  if (a === "kb-save") return kbSave();
  if (a === "rule-edit") { S.kbEdit = { kind: "rule", id: Number(act.dataset.id) }; return viewKnowledge(false); }
  if (a === "pref-edit") { S.kbEdit = { kind: "pref", id: Number(act.dataset.id) }; return viewKnowledge(false); }
  if (a === "pref-new") { S.kbEdit = { kind: "newpref" }; return viewKnowledge(false); }
  if (a === "pend-edit") { S.kbEdit = { kind: "pend", id: Number(act.dataset.id) }; return viewKnowledge(false); }
  if (a === "rule-del" || a === "pref-del") {
    const url = a === "rule-del" ? `/api/learnings/${act.dataset.id}` : `/api/prefs/${act.dataset.id}`;
    try { await api(url, { method: "DELETE" }); toast(a === "rule-del" ? "Kural silindi (arşivde saklanıyor)" : "Tercih silindi"); viewKnowledge(); }
    catch (err) { toast(err.message, true); }
    return;
  }
  if (a === "pend-add") {
    const id = Number(act.dataset.id), sel = $(`[data-pend-topic="${id}"]`), inp = $("#kbEditInput");
    const editing = S.kbEdit && S.kbEdit.kind === "pend" && S.kbEdit.id === id;
    return decideLearning(id, "onayla", { skill: sel ? sel.value : null, metin: editing && inp ? inp.value.trim() : null });
  }
  if (a === "pend-drop") return decideLearning(Number(act.dataset.id), "at");
  if (a === "lp-add") return decideLearning(Number(act.dataset.id), "onayla");
  if (a === "lp-skip") return decideLearning(Number(act.dataset.id), "at");
  if (a === "lp-edit") { S.lpEdit = Number(act.dataset.id); renderChat(); const i = $("#lpEditInput"); if (i) { autosize(i); i.focus(); } return; }
  if (a === "lp-cancel") { S.lpEdit = null; return renderChat(); }
  if (a === "lp-save") { const i = $("#lpEditInput"); return decideLearning(Number(act.dataset.id), "onayla", { metin: i ? i.value.trim() : null }); }
  if (a === "export-toggle") { S.exportOpen = !S.exportOpen; if (S.exportOpen) renderExport(); else $("#exportPop").hidden = true; return; }
  if (a === "export-seed") { S.exportSeed = S.exportSeed === false; return renderExport(); }
  if (a === "export-go") { download(`/api/learnings/export?baslangic=${S.exportSeed === false ? 0 : 1}`); S.exportOpen = false; $("#exportPop").hidden = true; return; }
  if (a === "generate" || a === "scope-open") return openScope();
  if (a === "scope-go") return scopeGo();
  if (a === "scope-alan") {
    const sc = S.scope, v = act.dataset.alan;
    sc.alanlar.has(v) ? sc.alanlar.delete(v) : sc.alanlar.add(v);
    scopeDefaults(sc); return renderScope();
  }
  if (a === "scope-more") { S.scope.more = !S.scope.more; return renderScope(); }
  if (a === "scope-org") { S.scope.org = !S.scope.org; return renderScope(); }
  if (a === "grp-more") { const k = act.dataset.key; S.showAll.has(k) ? S.showAll.delete(k) : S.showAll.add(k); return viewDocs(); }
  if (a === "doc-edit") { const id = Number(act.dataset.id); S.docEdit = S.docEdit === id ? null : id; return viewDocs(); }
  if (a === "doc-confirm") { S.docEdit = null; return editDoc(Number(act.dataset.id), {}); }
  if (a === "doc-alan-del") {
    const d = S.docs.find((x) => x.id === Number(act.dataset.id));
    S.docEdit = d.id;
    return editDoc(d.id, { alanlar: d.alanlar.filter((x) => x !== act.dataset.alan) });
  }
  if (a === "add-standard") { S.uploadAs = "lisansli"; $("#fileInput").click(); return; }
  if (a === "open-basis") {
    const c = findControl(S.selectedId); const b = c && (c.dayanak_bag || [])[Number(act.dataset.i)];
    if (b) return openDoc(b.doc_id, { quote: b.alinti, bolum: b.label, back: c.id });
    return;
  }
  if (a === "cancel") {
    act.disabled = true; act.textContent = "Durduruluyor…";
    try { await api(`/api/sets/${S.set.id}/cancel`, { method: "POST" }); } catch (err) { toast(err.message, true); }
    return;
  }
  if (a === "to-docs") return go("#/belgeler");
  if (a === "model-pick") return pickModel(act.dataset.conn, act.dataset.model);
  if (a === "model-manual") { const v = $(`[data-manual="${act.dataset.conn}"]`).value.trim(); if (v) pickModel(act.dataset.conn, v); return; }
  if (a === "conn-edit") { S.editConn = S.editConn === act.dataset.id ? null : act.dataset.id; return viewModel(false); }
  if (a === "conn-add") { S.addingConn = true; viewModel(false); const i = $('#addConn input[name="ad"]'); if (i) i.focus(); return; }
  if (a === "conn-add-cancel") { S.addingConn = false; return viewModel(false); }
  if (a === "conn-key-del") {
    try { S.models = await api("/api/models/connections", jsonOpts("POST", { id: act.dataset.id, anahtari_sil: true })); S.editConn = null; viewModel(false); toast("Anahtar silindi"); }
    catch (err) { toast(err.message, true); }
    return;
  }
  if (a === "conn-del") {
    if (!confirm("Bu bağlantı silinsin mi?")) return;
    try { S.models = await api("/api/models/connections/" + act.dataset.id, { method: "DELETE" }); S.editConn = null; viewModel(false); }
    catch (err) { toast(err.message, true); }
    return;
  }
  if (a === "del-doc") {
    if (S.docId === Number(act.dataset.id)) closePanel();
    try { await api("/api/documents/" + act.dataset.id, { method: "DELETE" }); S.docs = await api("/api/documents"); renderSidebar(); viewDocs(); }
    catch (err) { toast(err.message, true); }
    return;
  }
  if (a === "lib-word") return download("/api/library/export/word");
  if (a === "lib-excel") return download("/api/library/export/excel");
  if (a === "export-word") return download(`/api/export/word?set_id=${S.set.id}`);
  if (a === "export-excel") return download(`/api/export/excel?set_id=${S.set.id}`);
  if (a === "menu") { $("#menu").classList.toggle("open"); return; }
  if (a === "delete-set") {
    $("#menu").classList.remove("open");
    if (!confirm(`“${S.set.baslik || "Bu set"}” silinsin mi? Kontroller sayfasındaki kabul edilmiş kontroller korunur.`)) return;
    await api("/api/sets/" + S.set.id, { method: "DELETE" });
    S.set = null; await refreshSets(); toast("Set silindi"); go("#/"); return;
  }
  if (a === "lib-remove") {
    await api("/api/library/" + act.dataset.id, { method: "DELETE" });
    await refreshLib(); viewLibrary(); return;
  }

  const tabBtn = e.target.closest("[data-doc-tab]");
  if (tabBtn) { S.docTab = tabBtn.dataset.docTab; if (S.panelMode === "doc") closePanel(); viewDocs(); $("#scroll").scrollTop = 0; return; }
  const pick = e.target.closest("[data-pick]");
  if (pick && S.scope) {
    const set = pick.dataset.pick === "esas" ? S.scope.belgeler : S.scope.dayanak, id = Number(pick.dataset.id);
    set.has(id) ? set.delete(id) : set.add(id); return renderScope();
  }
  const docRow = e.target.closest(".doc-row[data-doc]");
  if (docRow && !e.target.closest("a, button, select, label, .classify")) {
    const id = Number(docRow.dataset.doc);
    if (S.panelMode === "doc" && S.docId === id) closePanel(); else openDoc(id);
    return;
  }

  const row = e.target.closest("#setBody .row");
  if (row) {
    const id = Number(row.dataset.id);
    if (e.metaKey || e.ctrlKey) {                       // çoklu seçim
      S.multi.has(id) ? S.multi.delete(id) : S.multi.add(id); S.anchor = id;
      syncRows(); renderBottom(); return;
    }
    if (e.shiftKey) {                                   // aralık seçimi
      const list = orderedVisible().map((c) => c.id);
      const from = list.indexOf(S.anchor ?? S.selectedId ?? id), to = list.indexOf(id);
      const [i, j] = from < 0 ? [to, to] : [Math.min(from, to), Math.max(from, to)];
      list.slice(i, j + 1).forEach((x) => S.multi.add(x));
      syncRows(); renderBottom(); return;
    }
    if (S.multi.size) clearMulti();
    if (S.changed.has(id)) { S.changed.delete(id); row.classList.remove("changed"); }
    if (S.selectedId === id && S.panelMode === "detail") closePanel(); else openPanel(id);
  }
});

document.addEventListener("change", (e) => {
  const tur = e.target.closest("[data-doc-tur]");
  if (tur) { S.docEdit = Number(tur.dataset.docTur); return editDoc(S.docEdit, { tur: tur.value }); }
  const al = e.target.closest("[data-doc-alan]");
  if (al && al.value) { const d = S.docs.find((x) => x.id === Number(al.dataset.docAlan)); S.docEdit = d.id; return editDoc(d.id, { alanlar: [...d.alanlar, al.value] }); }
});

document.addEventListener("input", (e) => {
  if (e.target.id === "scopeName" && S.scope) { S.scope.baslik = e.target.value; S.scope.nameTouched = true; }
  if (e.target.id === "ctrlSearch") { S.q = e.target.value; S.route.name === "kutuphane" ? viewLibrary() : renderSetBody(); }
  if (e.target.matches("textarea.auto") || e.target.id === "chatInput" || e.target.id === "kbEditInput" || e.target.id === "lpEditInput") autosize(e.target);
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
  if (e.key === "Enter" && !e.shiftKey && e.target.matches('textarea[data-field="kontrol_adi"], textarea[data-field="dayanak"], textarea[data-field="sorumlu"]')) { e.preventDefault(); e.target.blur(); }
  if (e.key === "Enter" && e.target.id === "scopeName") { e.preventDefault(); scopeGo(); }
  if (e.key === "Enter" && !e.shiftKey && e.target.id === "chatInput") { e.preventDefault(); sendChat(); }
  if (e.key === "Escape" && e.target.matches("textarea[data-field]")) { e.preventDefault(); e.target.blur(); }
});

$("#fileInput").addEventListener("change", (e) => { upload(e.target.files); e.target.value = ""; });
$("#secToggle").onclick = () => $("#secSets").classList.toggle("closed");
$("#newSetBtn").onclick = () => openScope();
$("#userBtn").onclick = () => go("#/model");
document.addEventListener("submit", (e) => {
  const f = e.target.closest("[data-conn-form]");
  if (f) { e.preventDefault(); saveConn(f); }
});
$("#searchBtn").onclick = () => { const i = $("#ctrlSearch"); if (i) i.focus(); else if (S.lib.length) go("#/kutuphane"); };
$("#askBar").onclick = openChat;

/* klavye: gezinme ve karar */
function moveSelection(dir) {
  const list = orderedVisible(); if (!list.length) return;
  const i = list.findIndex((c) => c.id === S.selectedId);
  const next = i < 0 ? list[dir > 0 ? 0 : list.length - 1] : list[Math.min(list.length - 1, Math.max(0, i + dir))];
  S.kbd = true;
  openPanel(next.id, { keepKbd: true });
  const row = document.querySelector(`.row[data-id="${next.id}"]`); if (row) row.scrollIntoView({ block: "nearest" });
}

document.addEventListener("keydown", (e) => {
  const mod = e.metaKey || e.ctrlKey;
  const k = e.key.toLowerCase();
  if (mod && k === "k") { e.preventDefault(); $("#searchBtn").click(); return; }
  if (mod && k === "j") { e.preventDefault(); S.panelMode === "chat" ? closeChat() : openChat(); return; }
  if (e.key === "Escape") {
    if (e.target.id === "kbEditInput") { S.kbEdit = null; return viewKnowledge(false); }
    if (S.exportOpen) { S.exportOpen = false; const pp = $("#exportPop"); if (pp) pp.hidden = true; return; }
    const menu = $("#menu");
    if (menu && menu.classList.contains("open")) return menu.classList.remove("open");
    if (S.multi.size) return clearMulti();
    if (S.panelMode === "chat") return closeChat();
    if (S.panelMode === "scope") return closePanel();
    if (S.panelMode === "doc") { if (S.docBack) { const id = S.docBack; S.panelMode = null; return openPanel(id); } return closePanel(); }
    if (S.selectedId) return closePanel();
    return;
  }
  if (e.target.id === "kbEditInput" && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); return kbSave(); }
  if (typing(e.target)) return;
  const onSet = S.route.name === "set" && S.set && !isGen(S.set);
  if (!onSet) return;
  if (mod && k === "z" && !e.shiftKey) { if (S.undo) { e.preventDefault(); undoLast(); } return; }
  if (mod || e.altKey) return;
  if (e.key === "ArrowDown" || k === "j") { e.preventDefault(); return moveSelection(1); }
  if (e.key === "ArrowUp" || k === "k") { e.preventDefault(); return moveSelection(-1); }
  if (k === "a" || k === "r") {
    e.preventDefault();
    const karar = k === "a" ? "kabul" : "red";
    if (S.multi.size) return decideMany([...S.multi], karar);
    if (S.selectedId) { S.kbd = true; return decide(S.selectedId, karar, { advance: true }); }
    return;
  }
  if (k === "e" && S.selectedId && S.panelMode === "detail") {
    e.preventDefault(); const t = $('#panel textarea[data-field="kontrol_adi"]'); if (t) { t.focus(); t.setSelectionRange(t.value.length, t.value.length); }
  }
  if (e.key === "Enter" && S.selectedId && S.panelMode !== "detail") { e.preventDefault(); S.panelMode = null; openPanel(S.selectedId, { keepKbd: true }); }
});

window.addEventListener("hashchange", route);

/* ---------------------------------------------------------------- başlat */
(async function init() {
  api("/api/health").then((h) => { S.health = h; renderHealth(); if (S.route.name === "belgeler") viewDocs(); }).catch(() => renderHealth());
  try { S.meta = await api("/api/meta"); } catch {}
  try { await loadBase(); } catch (e) { toast("Sunucuya ulaşılamadı", true); }
  const running = S.sets.find(isGen);
  if (running) startPoll(running.id);   // sayfa yenilendiyse üretimi izlemeye devam et
  route();
})();


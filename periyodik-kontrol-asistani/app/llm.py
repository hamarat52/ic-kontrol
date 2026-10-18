"""OpenAI-uyumlu (lokal) LLM uç noktasına çağrı.

Sabit bir cloud API key YOK. Uç nokta app/config.py üzerinden ortam
değişkenleriyle yapılandırılır (LLM_BASE_URL, LLM_MODEL, LLM_API_KEY).
Bağlantı kurulamazsa uygulama çökmez; çağıran taraf açık bir hata/durum alır.
"""
import json
import re
from typing import Iterator

import httpx

from . import config, model_settings

KATEGORILER = ["Operasyonel", "Mevzuat Uyum", "Bilgi Sistemleri", "Finansal Raporlama", "AML / Şüpheli İşlem"]
SIKLIKLAR = ["Anlık", "Günlük", "Haftalık", "Aylık", "Üç aylık", "Altı aylık", "Yıllık", "Olay tetiklemeli"]
RISKLER = ["Düşük", "Orta", "Yüksek", "Kritik"]
EFORLAR = ["Düşük", "Orta", "Yüksek"]
EDITABLE_FIELDS = ("kontrol_adi", "kategori", "hat", "siklik", "risk", "efor", "gerekce", "dayanak", "sorumlu")

SET_SYSTEM_PROMPT = f"""Sen bir bankanın iç kontrol biriminde periyodik kontrol tasarlayan \
kıdemli bir uzmansın. Sana şirketin bir süreç/prosedür belgesinden TEK BİR BÖLÜM ve birikmiş \
bilgi tabanı verilecek. Bu bölümde anlatılan süreçler için somut, test edilebilir periyodik \
kontroller öner.

BÖLÜMÜ OKUMA: Bölüm birden fazla alt başlık içerebilir ve bir başlığın ortasından başlayabilir. \
HER alt başlığı ayrı değerlendir. İlk alt başlık "Amaç", "Kapsam" ya da "Tanımlar" olsa bile \
sonraki alt başlıkları atlama.

KATEGORİ (birini seç):
- Operasyonel: talimat, onay zinciri, işlem girişi, mutabakat, iade, teminat, kullandırım gibi işin doğru ve zamanında yapılması.
- Mevzuat Uyum: kanun/yönetmelik sınırları, düzenleyici bildirim ve raporlar, kayıt saklama süreleri.
- Bilgi Sistemleri: kullanıcı erişimi, yetki atama/gözden geçirme, parola, log, ayrıcalıklı hesap, sistem parametresi, görevler ayrılığının sistemde uygulanması.
- Finansal Raporlama: muhasebe kaydı, hesap mutabakatının finansal tablolara yansıması, yönetim raporlaması.
- AML / Şüpheli İşlem: şüpheli işlem bildirimi (MASAK), yaptırım listesi taraması, müşteri tanıma.

HAT (kontrolü periyodik olarak kim YAPAR):
- 1: işi yapan ya da sahibi olan birim kendi işini gözden geçirir (şube, operasyon, BT'nin yetki \
gözden geçirmesi, ilgili müdürlüğün aylık kontrolü). Belgede işi yapan birimin yaptığı gözden geçirmeler Hat 1'dir.
- 2: iç kontrol, uyum, risk yönetimi veya bilgi güvenliği birimi birinci hattın kontrolünü test eder ya da izler.
- 3: teftiş kurulu bağımsız denetim yapar.
Hepsini aynı hatta toplama; her kontrolü yapan birime göre ayrı değerlendir.

DAYANAK ADAYLARI: Mesajda [1], [2]… diye numaralanmış mevzuat maddeleri ve standartlar verilebilir. \
Bunlardan kontrol ÜRETME; kontroller yalnız BÖLÜM METNİ'nden çıkar. Bir kontrol bir adayla gerçekten \
ilgiliyse "dayanak_no" alanına adayın numarasını, "dayanak" alanına kısa adını ve maddesini yaz \
(ör. "BDDK Bilgi Sistemleri Yönetmeliği m.11"). İlgisizse ikisini de boş bırak. Listede olmayan madde uydurma.

ŞİRKET ORGANİZASYONU: Verilirse "sorumlu" alanına kontrolü yapan birimin adını organizasyon metnindeki \
gibi yaz ve hattı o birime göre seç. Verilmezse bölüm metninde geçen birimi yaz; o da yoksa boş bırak.

SIKLIK: Belgede süre ya da sıklık geçiyorsa (günlük, haftalık, aylık, altı ayda bir, yılda bir, \
ertesi iş günü, gün sonu) ona uygun değeri seç. Geçmiyorsa riske ve işlem hacmine göre seç.

KONTROL ADI: neyin nasıl test edileceğini söyleyen kısa bir ifade. \
İyi: "Mesai dışı işlemlerin ertesi gün listelenip incelendiğinin teyidi". Kötü: "Log İzleme". \
Aynı kontrolü farklı adlarla tekrar etme.

ÇIKTI BİÇİMİ — ÇOK ÖNEMLİ: JSON Lines. Her satır tek bir JSON objesi. Başka hiçbir metin, \
açıklama, liste parantezi veya kod bloğu yazma.

Her kontrol için bir satır:
{{"tip":"kontrol","kontrol_adi":"...","kategori":"<{' | '.join(KATEGORILER)}>","hat":"<1, 2 veya 3>","siklik":"<{' | '.join(SIKLIKLAR)}>","risk":"<{' | '.join(RISKLER)}>","efor":"<{' | '.join(EFORLAR)}>","gerekce":"<neden gerekli, en fazla 2 cümle>","dayanak":"<dayanak adayının kısa adı ve maddesi; yoksa boş>","dayanak_no":[<ilgili aday numaraları>],"sorumlu":"<kontrolü yapan birim ya da boş>","kaynak":"<bu bölümden kısa BİREBİR alıntı ya da boş>"}}

Bölümde gerçek bir boşluk/tutarsızlık görürsen (ör. tanımlı bir adımı atlayan yol, süresi \
belirtilmemiş bir takip) bir satır:
{{"tip":"bosluk","metin":"<tek cümle>"}}

Yalnız bölümün TAMAMI amaç/kapsam/tanım ise sadece şunu yaz: {{"tip":"yok"}}

Kurallar: kategori, sıklık, risk ve efor değerlerini YALNIZ yukarıdaki listelerden seç. \
Kaynak alıntısını uydurma; bölümde kelimesi kelimesine geçmiyorsa boş bırak. Bölümde \
dayanağı olmayan genel kontroller üretme. AML / Şüpheli İşlem kontrollerinin gerekçesine \
tipping-off (5549 m.4/2) riskini ekle. Bilgi tabanındaki "Öğrenilenler" maddelerini uygula."""

SUMMARY_SYSTEM_PROMPT = """Bir kontrol seti için kısa başlık ve özet yaz. SADECE şu JSON objesini \
döndür, başka metin yazma:
{"baslik":"<incelenen süreç(ler)in kısa adı, en fazla 6 kelime>","ozet":"<2-3 cümle: hangi \
belgeler incelendi, kontroller nerede yoğunlaşıyor, öne çıkan boşluk varsa ne>"}"""

RULE_SYSTEM_PROMPT = """Bir bankanın iç kontrol uzmanının bir kontrol setindeki kararlarına bakıp, \
gelecekteki setlerde de uygulanacak GENEL bir kural çıkarıp çıkaramayacağına karar veriyorsun.

Kural: tek cümle, genel (tek bir kontrolün adını içermez), uygulanabilir (model yeni kontrol önerirken \
neyi farklı yapacağını söyler). Kararlarda ortak bir örüntü YOKSA ya da sebep belirsizse kural uydurma.

SADECE şu JSON'u döndür: {"kural":"<tek cümle ya da null>","gerekce":"<hangi kararlardan çıkardın, kısa>"}"""

CHAT_SYSTEM_PROMPT = """Sen bir bankanın iç kontrol biriminde, kullanıcının bir kontrol setine \
veya tek bir kontrole verdiği serbest metin geri bildirimini uygulayan bir uzmansın.

Sana setteki kontroller (id ile), varsa odaktaki kontrol ve kullanıcının mesajı verilecek. \
SADECE geçerli bir JSON objesi döndür, başka hiçbir metin yazma:

{"yanit":"<kullanıcıya kısa Türkçe yanıt: ne yaptın, neyi neden değiştirmedin>",
 "degisiklikler":[{"id":<kontrol id>,"alanlar":{"<alan>":"<yeni değer>"}}],
 "ders":"<kullanıcının mesajından çıkan, gelecekteki setlere de uygulanabilecek GENEL tek cümlelik kural; \
tek seferlik bir düzeltmeyse null>"}

Değiştirilebilir alanlar: kontrol_adi, kategori, hat, siklik, risk, efor, gerekce, dayanak, sorumlu. \
Değişiklik gerekmiyorsa "degisiklikler": [] döndür. Yalnız verilen id'leri kullan. \
Kategori/sıklık/risk/efor için mevcut değerlerle aynı sözlüğü kullan."""


def _conn(conn: dict | None) -> dict:
    return conn or model_settings.active()


def _url(conn: dict):
    return f"{conn['base_url'].rstrip('/')}/chat/completions"


def connection_error_text(err: str, conn: dict | None = None) -> str:
    c = _conn(conn)
    return (f"Modele ulaşılamadı ({c.get('ad')}: {c.get('base_url')}, model: {c.get('model')}): {err}. "
            "Model ayarlarını kontrol edin.")


def _extract_json_payload(content: str):
    """Model çıktısını (gerekirse kod bloğundan temizleyip) json.loads ile ayrıştırır."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # metnin içindeki ilk { ... } ya da [ ... ] bloğunu dene
        m = re.search(r"(\{.*\}|\[.*\])", cleaned, re.S)
        if not m:
            raise
        return json.loads(m.group(1))


def call_chat_completion(messages: list[dict], temperature: float = 0.2, conn: dict | None = None) -> dict:
    """Döner: {"ok": True, "content": str} veya {"ok": False, "error": str}."""
    conn = _conn(conn)
    payload = {"model": conn["model"], "messages": messages, "temperature": temperature, "max_tokens": 4096}
    try:
        with httpx.Client(timeout=config.LLM_TIMEOUT_S) as client:
            resp = client.post(_url(conn), json=payload, headers=model_settings.headers(conn))
            resp.raise_for_status()
            return {"ok": True, "content": resp.json()["choices"][0]["message"]["content"]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------- normalizasyon

def _pick(value, options, default):
    if not value:
        return default
    v = str(value).strip().lower()
    for opt in options:
        if v == opt.lower():
            return opt
    for opt in options:  # kısmi eşleşme ("yuksek", "aml" vb.)
        o = opt.lower()
        if v in o or o.split()[0] in v:
            return opt
    tr = str.maketrans("ışğüöç", "isguoc")
    for opt in options:
        if v.translate(tr) == opt.lower().translate(tr):
            return opt
    return default


def normalize_control(obj: dict) -> dict:
    hat = re.search(r"[123]", str(obj.get("hat") or ""))
    return {
        "kontrol_adi": (obj.get("kontrol_adi") or "").strip() or "Adsız kontrol",
        "kategori": _pick(obj.get("kategori"), KATEGORILER, "Operasyonel"),
        "hat": hat.group(0) if hat else "1",
        "siklik": _pick(obj.get("siklik"), SIKLIKLAR, "Aylık"),
        "risk": _pick(obj.get("risk"), RISKLER, "Orta"),
        "efor": _pick(obj.get("efor"), EFORLAR, "Orta"),
        "gerekce": (obj.get("gerekce") or "").strip(),
        "dayanak": (obj.get("dayanak") or "").strip(),
        "dayanak_no": _nums(obj.get("dayanak_no")),
        "sorumlu": (obj.get("sorumlu") or "").strip()[:120],
        "kaynak": (obj.get("kaynak") or "").strip(),
    }


def _nums(v) -> list[int]:
    if isinstance(v, (int, float)):
        v = [v]
    if isinstance(v, str):
        v = re.findall(r"\d+", v)
    out = []
    for x in v or []:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n not in out:
            out.append(n)
    return out


def normalize_fields(fields: dict) -> dict:
    out = {}
    for k, v in (fields or {}).items():
        if k not in EDITABLE_FIELDS or v in (None, ""):
            continue
        if k == "kategori":
            v = _pick(v, KATEGORILER, None)
        elif k == "siklik":
            v = _pick(v, SIKLIKLAR, None)
        elif k == "risk":
            v = _pick(v, RISKLER, None)
        elif k == "efor":
            v = _pick(v, EFORLAR, None)
        elif k == "hat":
            m = re.search(r"[123]", str(v))
            v = m.group(0) if m else None
        else:
            v = str(v).strip()
        if v:
            out[k] = v
    return out


# ---------------------------------------------------------------- set üretimi (akışlı)

def _parse_line(line: str):
    line = line.strip().strip(",")
    if not line or line.startswith("```"):
        return None
    if not line.startswith("{"):
        i = line.find("{")
        if i < 0:
            return None
        line = line[i:]
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _classify(obj: dict):
    tip = (obj.get("tip") or "").lower()
    if tip == "yok":
        return {"event": "empty"}
    if tip == "baslik" or ("baslik" in obj and "kontrol_adi" not in obj):
        return {"event": "meta", "baslik": obj.get("baslik") or "", "ozet": obj.get("ozet") or ""}
    if tip == "bosluk" or ("metin" in obj and "kontrol_adi" not in obj):
        return {"event": "gap", "metin": obj.get("metin") or ""}
    if tip == "kontrol" or "kontrol_adi" in obj:
        return {"event": "control", "control": normalize_control(obj)}
    return None


def stream_control_set(chunk_text: str, skills_text: str, context: dict | None = None,
                       should_stop=None, examples: str = "", hint: str = "",
                       conn: dict | None = None, basis: str = "", org: str = "") -> Iterator[dict]:
    """Bir bölüm için model çıktısını satır satır okuyup olay üretir:
    {"event":"control"|"gap"|"meta"|"empty"|"error", ...}. Asla exception fırlatmaz.
    `should_stop()` True dönerse akışı keser. `examples`: kurumun kabul/ret geçmişi,
    `hint`: boş dönen bölümü yeniden denerken eklenen uyarı. `basis`: numaralı dayanak adayları
    (mevzuat/standart maddeleri), `org`: ilgili organizasyon/görev tanımı parçaları."""
    ctx = context or {}
    where = ""
    if ctx:
        where = (f"BELGE: {ctx.get('belge', '')}\nBÖLÜM: {ctx.get('bolum', '')} "
                 f"({ctx.get('index', 0) + 1}/{ctx.get('toplam', 1)})\n")
    messages = [
        {"role": "system", "content": SET_SYSTEM_PROMPT},
        # Sabit kısım (bilgi tabanı) önce: yerel sunucular ortak öneki önbellekleyebilir.
        {"role": "user", "content": (
            f"BİLGİ TABANI (skill'ler):\n{skills_text}\n\n"
            + (f"{examples}\n\n" if examples else "")
            + (f"{org}\n\n" if org else "")
            + (f"{basis}\n\n" if basis else "")
            + f"{where}BÖLÜM METNİ:\n{chunk_text}\n\n"
            + (f"{hint}\n\n" if hint else "")
            + "Şimdi JSON Lines çıktısını üret."
        )},
    ]
    conn = _conn(conn)
    payload = {"model": conn["model"], "messages": messages, "temperature": 0.2, "stream": True, "max_tokens": 8192}
    buffer, full = "", ""
    emitted = 0
    stop = should_stop or (lambda: False)
    try:
        with httpx.Client(timeout=httpx.Timeout(config.LLM_TIMEOUT_S, connect=10)) as client:
            with client.stream("POST", _url(conn), json=payload, headers=model_settings.headers(conn)) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    yield {"event": "error", "error": connection_error_text(f"HTTP {resp.status_code}: {resp.text[:200]}", conn)}
                    return
                for raw in resp.iter_lines():
                    if stop():
                        return
                    if not raw or not raw.startswith("data:"):
                        continue
                    data = raw[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content") or ""
                    except Exception:
                        continue
                    buffer += delta
                    full += delta
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        obj = _parse_line(line)
                        ev = _classify(obj) if obj else None
                        if ev:
                            emitted += 1
                            yield ev
    except Exception as exc:
        yield {"event": "error", "error": connection_error_text(str(exc), conn)}
        return

    obj = _parse_line(buffer)
    ev = _classify(obj) if obj else None
    if ev:
        emitted += 1
        yield ev

    if emitted == 0 and full.strip():
        # Model JSON Lines yerine tek bir JSON (liste/obje) döndürdüyse kurtarmayı dene.
        try:
            parsed = _extract_json_payload(full)
            items = parsed if isinstance(parsed, list) else parsed.get("kontroller", [parsed])
            for it in items:
                if isinstance(it, dict):
                    ev = _classify(it) or {"event": "control", "control": normalize_control(it)}
                    yield ev
                    emitted += 1
        except Exception:
            pass
    if emitted == 0:
        yield {"event": "error", "error": "Model bu bölüm için geçerli bir çıktı vermedi (biçim hatası)."}


def summarize_set(doc_names: list[str], headings: list[str], titles: list[str], gaps: list[str],
                  conn: dict | None = None) -> dict | None:
    """Set başlığı ve özeti; başarısızlıkta None (çağıran geçici başlığı korur)."""
    user = (
        f"BELGELER: {', '.join(doc_names)}\n"
        f"BÖLÜMLER: {'; '.join(headings[:40])}\n"
        f"KONTROLLER ({len(titles)}): {'; '.join(titles[:60])}\n"
        f"BOŞLUKLAR: {'; '.join(gaps[:10]) or 'yok'}"
    )
    result = call_chat_completion(
        [{"role": "system", "content": SUMMARY_SYSTEM_PROMPT}, {"role": "user", "content": user}], conn=conn
    )
    if not result["ok"]:
        return None
    try:
        parsed = _extract_json_payload(result["content"])
        baslik = str(parsed.get("baslik") or "").strip().strip('"')[:80]
        ozet = str(parsed.get("ozet") or "").strip()
        return {"baslik": baslik, "ozet": ozet} if baslik else None
    except Exception:
        return None


def propose_rule(rejected: list[dict], edits: list[str], accepted: list[str], conn: dict | None = None) -> dict | None:
    """Ret ve düzeltmelerden genel kural önerisi; yoksa None."""
    lines = []
    if rejected:
        lines.append("REDDEDİLEN KONTROLLER:")
        lines += [f"- {r['kontrol_adi']} (kategori {r['kategori']}, hat {r['hat']}, sıklık {r['siklik']}"
                  f"{', sorumlu ' + r['sorumlu'] if r.get('sorumlu') else ''})" for r in rejected]
    if edits:
        lines.append("KULLANICININ DÜZELTMELERİ (alan: eski → yeni):")
        lines += [f"- {e}" for e in edits]
    if accepted:
        lines.append("KARŞILAŞTIRMA İÇİN KABUL EDİLENLER:")
        lines += [f"- {a}" for a in accepted[:10]]
    result = call_chat_completion([{"role": "system", "content": RULE_SYSTEM_PROMPT},
                                   {"role": "user", "content": "\n".join(lines)}], conn=conn)
    if not result["ok"]:
        return None
    try:
        parsed = _extract_json_payload(result["content"])
    except Exception:
        return None
    kural = parsed.get("kural") if isinstance(parsed, dict) else None
    if not isinstance(kural, str) or kural.strip().lower() in ("", "null", "none"):
        return None
    return {"kural": kural.strip(), "gerekce": str(parsed.get("gerekce") or "").strip()}


# ---------------------------------------------------------------- sohbet / geri bildirim

def chat_feedback(controls: list[dict], focus: dict | None, message: str, skills_text: str,
                  conn: dict | None = None) -> dict:
    compact = [
        {k: c.get(k) for k in ("id", "kontrol_adi", "kategori", "hat", "siklik", "risk", "efor")}
        for c in controls
    ]
    user = (
        f"BİLGİ TABANI (özet):\n{skills_text[:3500]}\n\n"
        f"SETTEKİ KONTROLLER:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
        + (f"ODAKTAKİ KONTROL (mesaj özellikle bununla ilgili):\n{json.dumps(focus, ensure_ascii=False)}\n\n" if focus else "")
        + f"KULLANICI MESAJI:\n{message}"
    )
    result = call_chat_completion(
        [{"role": "system", "content": CHAT_SYSTEM_PROMPT}, {"role": "user", "content": user}], conn=conn
    )
    if not result["ok"]:
        return {"ok": False, "error": connection_error_text(result["error"])}
    try:
        parsed = _extract_json_payload(result["content"])
        if not isinstance(parsed, dict):
            raise ValueError("obje bekleniyordu")
    except Exception as exc:
        return {"ok": False, "error": f"Model yanıtı ayrıştırılamadı: {exc}"}
    ders = parsed.get("ders")
    if isinstance(ders, str) and ders.strip().lower() in ("null", "none", ""):
        ders = None
    return {
        "ok": True,
        "yanit": (parsed.get("yanit") or "").strip() or "Tamam.",
        "degisiklikler": parsed.get("degisiklikler") or [],
        "ders": ders,
    }

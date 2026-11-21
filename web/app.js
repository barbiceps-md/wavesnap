"use strict";
/* WaveSnap arayüzü — derleme adımı yok, düz JavaScript. */
const $ = (s, k = document) => k.querySelector(s);
const $$ = (s, k = document) => [...k.querySelectorAll(s)];
const S = { veri: null, sayfa: "genel", filtre: "bagli", arama: "", mesgul: false, cekmece: null, surukle: null };
const SINIRLAR = [1, 2, 5, 10, 20];
const SAYFALAR = {
  genel: ["Genel bakış", "Ağınızın şu anki hali"],
  cihazlar: ["Cihazlar", "Bağlı ve daha önce bağlanmış bütün cihazlar"],
  gecmis: ["Geçmiş", "Kullanım, bağlantı ve kesinti geçmişi"],
  zamanlama: ["Zamanlama", "Belirli saatlerde internet ve Wi-Fi"],
  misafir: ["Misafir ağı", "Müşteriler için ayrı Wi-Fi"],
  araclar: ["Araçlar", "Hız testi, tanılama, modem"],
  ayarlar: ["Ayarlar", "Tema, bildirimler ve modem bağlantısı"],
};
// ---------- biçimlendirme ----------
const sayi = (n, b = 1) => n.toLocaleString(YEREL(), { minimumFractionDigits: b, maximumFractionDigits: b });
function bayt(n) {
  if (!n) return "0 B";
  if (n < 1e3) return n + " B";
  if (n < 1e6) return sayi(n / 1e3, 0) + " KB";
  if (n < 1e9) return sayi(n / 1e6, n < 1e8 ? 1 : 0) + " MB";
  return sayi(n / 1e9, 2) + " GB";
}
function hizParca(bps) {
  if (!bps || bps < 2000) return ["0", "Mbps"];
  if (bps < 1e6) return [sayi(bps / 1e3, 0), "kbps"];
  return [sayi(bps / 1e6, bps < 1e7 ? 1 : 0), "Mbps"];
}
const hiz = bps => (!bps || bps < 2000) ? "boşta" : hizParca(bps).join(" ");
const saat = d => d.toLocaleTimeString(YEREL(), { hour: "2-digit", minute: "2-digit" });
function gun(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), simdi = new Date();
  const fark = Math.round((new Date(simdi.getFullYear(), simdi.getMonth(), simdi.getDate()) - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 864e5);
  if (fark === 0) return "bugün " + saat(d);
  if (fark === 1) return "dün " + saat(d);
  return d.toLocaleDateString(YEREL(), { day: "numeric", month: "short" }) + " " + saat(d);
}
function once(ts) {
  if (!ts) return "henüz okunmadı";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 5) return "az önce";
  if (s < 60) return s + " sn önce";
  if (s < 3600) return Math.round(s / 60) + " dk önce";
  return gun(ts);
}
function sure(baslangic) {
  if (!baslangic) return "";
  let s = Math.max(0, Date.now() / 1000 - baslangic);
  const g = Math.floor(s / 86400); s -= g * 86400;
  const sa = Math.floor(s / 3600); s -= sa * 3600;
  const dk = Math.floor(s / 60);
  return g ? `${g} gün ${sa} sa` : sa ? `${sa} sa ${dk} dk` : `${dk} dk`;
}
function ek(n) {  // "3'ü", "2'si"
  const son = n % 10, onlar = n % 100 - son;
  if (son === 0) return ({ 0: "'ı", 10: "'u", 20: "'si", 30: "'u", 40: "'ı", 50: "'si", 60: "'ı", 70: "'i", 80: "'i", 90: "'ı" })[onlar];
  return ({ 1: "'i", 2: "'si", 3: "'ü", 4: "'ü", 5: "'i", 6: "'sı", 7: "'si", 8: "'i", 9: "'u" })[son];
}
const ad = c => c.ad || c.host_adi || "Tanınmayan cihaz";
const bantYazi = c => !c.aktif ? (c.engelli ? "Engelli" : "Çevrim dışı") : c.tur === "kablo" ? "Kablo" : c.tur === "bilinmiyor" ? "Ağda" : c.bant === "5" ? "5 GHz" : c.bant === "2.4" ? "2,4 GHz" : "Wi-Fi";
const bantSinif = c => !c.aktif ? "yok" : c.tur === "kablo" || c.tur === "bilinmiyor" ? "kb" : c.bant === "5" ? "b5" : "b2";
// modem sürücüsünün yetenekleri: desteklenmeyen düğme ve bölümler gizlenir
const yetenek = y => !!(S.veri && S.veri.surucu && S.veri.surucu.yetenekler.includes(y));
const temelMod = () => !!(S.veri && S.veri.surucu && !S.veri.surucu.giris);
function yetenekleriUygula() {
  if (!S.veri || !S.veri.surucu) return;
  document.documentElement.classList.toggle("sayacsiz", !yetenek("sayac"));
  $$("[data-yetenek]").forEach(e => {
    const var_ = e.dataset.yetenek.split(" ").some(yetenek);
    if (var_) e.removeAttribute("data-yetenek-yok"); else e.setAttribute("data-yetenek-yok", "");
  });
  $("#birakSatir").hidden = !S.veri.surucu.tek_oturum;
}
const CINSLER = [["telefon", "Telefon"], ["bilgisayar", "Bilgisayar"], ["tablet", "Tablet"], ["tv", "TV"], ["yazici", "Yazıcı"],
  ["kamera", "Kamera"], ["oyun", "Oyun"], ["akilli", "Akıllı ev"], ["ag", "Ağ cihazı"], ["diger", "Diğer"]];
const tur = c => c.cins || "diger";
function el(etiket, sinif, metin) {
  const e = document.createElement(etiket);
  if (sinif) e.className = sinif;
  if (metin != null) e.textContent = metin;
  return e;
}
function svgKullan(id, sinif) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  if (sinif) s.setAttribute("class", sinif);
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", "#" + id);
  s.append(u);
  return s;
}
const yaz = (e, m) => { if (e && e.textContent !== m) e.textContent = m; };

// ---------- sunucu ----------
async function api(yol, govde) {
  const r = await fetch(yol, govde === undefined ? { cache: "no-store" } : {
    method: "POST", headers: { "Content-Type": "application/json", "X-Panel": "1" }, body: JSON.stringify(govde),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.hata || "İstek başarısız (" + r.status + ")");
  return j;
}
let yukleniyor = false, hataSayisi = 0;
async function tazele() {
  if (yukleniyor) return;
  yukleniyor = true;
  let v;
  try { v = await api("/api/durum"); hataSayisi = 0; }
  catch (e) {
    if (++hataSayisi >= 2) seritGoster("WaveSnap'in arka planı kapalı. Masaüstündeki WaveSnap simgesiyle yeniden açın.", [], true);
    durumGoster("kotu", "Bağlantı yok");
    return;
  } finally { yukleniyor = false; }
  // çizim hatası bağlantı hatası değildir: konsola yaz, "arka plan kapalı" deme
  try { ciz(v); } catch (e) { console.error("WaveSnap çizim hatası:", e); }
}

// ---------- tema ----------
function temaUygula(t, kaydet) {
  document.documentElement.dataset.tema = t;
  try { localStorage.setItem("ws-tema", t); } catch (e) {}
  $$("#temalar button").forEach(b => b.classList.toggle("secili", b.dataset.tema === t));
  if (S.veri) grafikCiz(S.veri.trafik || []);
  if (kaydet) api("/api/ayar", { tema: t }).catch(() => {});
}
$$("#temalar button").forEach(b => b.onclick = () => temaUygula(b.dataset.tema, true));

// ---------- sayfalar ----------
function sayfaAc(ad) {
  if (!SAYFALAR[ad]) ad = "genel";
  S.sayfa = ad;
  if (S.cekmece) cekmeceKapat();
  $$(".sayfa").forEach(s => s.hidden = s.dataset.sayfa !== ad || !S.veri || !S.veri.kurulu || !S.veri.son_okuma && ad !== "ayarlar");
  $$("[data-sayfa]").forEach(a => a.tagName === "A" && a.classList.toggle("secili", a.dataset.sayfa === ad));
  yaz($("#sayfaBaslik"), SAYFALAR[ad][0]);
  yaz($("#sayfaAlt"), SAYFALAR[ad][1]);
  $("#aramaKutu").hidden = !(ad === "genel" || ad === "cihazlar");
  if (S.veri) ciz(S.veri);
  if (typeof sayfaYukle === "function") sayfaYukle(ad);
}
window.addEventListener("hashchange", () => sayfaAc(location.hash.slice(1)));
$("#arama").addEventListener("input", e => { S.arama = e.target.value.trim().toLowerCase(); if (S.veri) ciz(S.veri); });
$$("#filtreler button").forEach(b => b.onclick = () => {
  S.filtre = b.dataset.f;
  $$("#filtreler button").forEach(x => x.classList.toggle("secili", x === b));
  ciz(S.veri);
});

// ---------- çizim ----------
function ciz(v) {
  S.veri = v;
  if (v.ayar && v.ayar.tema && v.ayar.tema !== document.documentElement.dataset.tema && !S.temaOkundu) temaUygula(v.ayar.tema);
  S.temaOkundu = true;
  const kurulumda = !v.kurulu || S.kurulumZorla;
  $("#kurulum").hidden = !kurulumda;
  $("#yukleme").hidden = kurulumda || !!v.son_okuma;
  $$(".sayfa").forEach(s => s.hidden = kurulumda || s.dataset.sayfa !== S.sayfa || (!v.son_okuma && S.sayfa !== "ayarlar"));
  if (v.surucu) yetenekleriUygula();
  const modelAd = v.hat && [v.hat.uretici, v.hat.model].filter(Boolean).join(" ");
  yaz($("#modemAd"), modelAd || (temelMod() ? "Temel mod" : "Modem"));
  if (v.surucu) yaz($("#baglantiOzet"), `${t(v.surucu.ad)} · ${v.modem_adres}`);
  $("#bildirimAnahtar").classList.toggle("acik", !!v.bildirim);
  if (kurulumda) {
    if (!S.kesif) kesifYap();
    $("#kVazgec").hidden = !v.kurulu;
    if (v.mesaj && !v.kurulu) { $("#kurulumHata").textContent = v.mesaj; $("#kurulumHata").hidden = false; }
    durumGoster("uyari", "Kurulum bekliyor");
    seritGizle();
    return;
  }
  durumVeSerit(v);
  if (!v.son_okuma) return;

  const sira = (v.ayar && v.ayar.sira) || [];
  const yer = mac => { const i = sira.indexOf(mac); return i < 0 ? -1 : i; };
  const siralama = (a, b) => {
    const ya = yer(a.mac), yb = yer(b.mac);
    if (ya !== yb && (ya < 0 || yb < 0)) return ya < 0 ? -1 : 1;  // sıraya henüz konmamışlar (yeniler) en üstte
    if (ya !== yb) return ya - yb;
    return ((a.tur === "kablo") - (b.tur === "kablo")) || ad(a).localeCompare(ad(b), "tr");
  };
  const ara = c => !S.arama || [ad(c), c.host_adi, c.ip, c.mac].join(" ").toLowerCase().includes(S.arama);
  const bagli = v.cihazlar.filter(c => c.aktif && !c.engelli).sort(siralama);
  yaz($("#rozetCihaz"), bagli.length ? String(bagli.length) : "");

  if (S.sayfa === "genel") {
    ozetCiz(v, bagli);
    grafikCiz(v.trafik || []);
    enlerCiz(bagli);
    tabloCiz($("#tabloGenel"), bagli.filter(ara), true);
  }
  if (S.sayfa === "cihazlar") {
    const gruplar = {
      bagli, tumu: [...v.cihazlar].sort(siralama),
      eski: v.cihazlar.filter(c => !c.aktif && !c.engelli).sort((a, b) => (b.son || 0) - (a.son || 0)),
      engelli: v.cihazlar.filter(c => c.engelli).sort(siralama),
    };
    $$("#filtreler button").forEach(b => yaz(b.querySelector("span"), String(gruplar[b.dataset.f].length)));
    grupFiltreCiz(v.cihazlar);
    const grupUy = c => !S.grup || c.grup === S.grup;
    tabloCiz($("#tabloCihaz"), gruplar[S.filtre].filter(ara).filter(grupUy), (S.filtre === "bagli" || S.filtre === "tumu") && !S.grup);
  }
  if (S.sayfa === "araclar" && typeof araclarCiz === "function") araclarCiz();
  if (S.cekmece) cekmeceCiz(S.cekmece);
}

function grupFiltreCiz(cihazlar) {
  const gruplar = [...new Set(cihazlar.map(c => c.grup).filter(Boolean))].sort((a, b) => a.localeCompare(b, "tr"));
  const kutu = $("#grupFiltre"), imza = gruplar.join("|") + "#" + (S.grup || "");
  kutu.hidden = !gruplar.length;
  if (kutu.dataset.imza === imza) return;
  kutu.dataset.imza = imza;
  const tum = el("button", S.grup ? "" : "secili", "Bütün gruplar");
  tum.onclick = () => { S.grup = ""; ciz(S.veri); };
  kutu.replaceChildren(el("span", "", "Grup:"), tum, ...gruplar.map(g => {
    const b = el("button", S.grup === g ? "secili" : "", g);
    b.onclick = () => { S.grup = g; ciz(S.veri); };
    return b;
  }));
}


function durumGoster(sinif, metin) { $("#durum").className = "modem-durum " + sinif; yaz($("#durumYazi"), metin); }
function durumVeSerit(v) {
  const y = { canli: ["canli", "Canlı · " + once(v.son_okuma)], baslatiliyor: ["", "Bağlanıyor…"], mesgul: ["uyari", "Modem meşgul"],
    duraklatildi: ["uyari", "Duraklatıldı"], ulasilamiyor: ["kotu", "Modeme ulaşılamıyor"], hata: ["kotu", "Okuma hatası"] }[v.durum] || ["", v.durum];
  durumGoster(...y);
  if (v.durum === "mesgul") seritGoster(v.mesaj, [["Yine de bağlan", () => api("/api/devam", { zorla: true }).then(tazele)]]);
  else if (v.durum === "duraklatildi") seritGoster(`WaveSnap modemi bıraktı; modemin kendi sayfasına girebilirsiniz. ${Math.ceil(v.duraklat_kalan / 60)} dk sonra kendiliğinden devam eder.`, [["Şimdi devam et", () => api("/api/devam", {}).then(tazele)]]);
  else if (v.durum === "ulasilamiyor" || v.durum === "hata") seritGoster(v.mesaj + (v.son_okuma ? " Gördüğünüz veriler son başarılı okumadan." : ""), [], true);
  else seritGizle();
}
function seritGoster(metin, dugmeler, kotu) {
  $("#serit").classList.toggle("kotu", !!kotu);
  yaz($("#seritYazi"), metin);
  const kutu = $("#seritDugmeler"), imza = dugmeler.map(d => d[0]).join("|");
  if (kutu.dataset.imza !== imza) {
    kutu.replaceChildren(...dugmeler.map(([a, is]) => { const b = el("button", "dugme", a); b.onclick = is; return b; }));
    kutu.dataset.imza = imza;
  }
  $("#serit").hidden = false;
}
const seritGizle = () => $("#serit").hidden = true;

function ozetCiz(v, bagli) {
  yaz($("#oBagli"), String(bagli.length));
  yaz($("#oBagliBaslik"), temelMod() ? "Görülen cihaz" : "Bağlı cihaz");
  $("#oDagilim").hidden = temelMod();
  if (temelMod()) yaz($("#oDagilimYazi"), "son 10 dakikada ağda görülenler");
  const b5 = bagli.filter(c => c.tur === "wifi" && c.bant === "5").length;
  const b2 = bagli.filter(c => c.tur === "wifi" && c.bant !== "5").length;
  const kb = bagli.filter(c => c.tur === "kablo").length;
  const d = $("#oDagilim");
  if (d.children.length !== 3) d.replaceChildren(el("i"), el("i"), el("i"));
  [b5, b2, kb].forEach((n, i) => d.children[i].style.flexGrow = n);
  const tr = CEVIRI.dil === "tr";
  const parca = tr ? [b5 && `${b5}${ek(b5)} 5 GHz`, b2 && `${b2}${ek(b2)} 2,4 GHz`, kb && `${kb}${ek(kb)} kablo`]
    : [b5 && `5 GHz: ${b5}`, b2 && `2.4 GHz: ${b2}`, kb && `${t("Kablo")}: ${kb}`];
  parca.splice(0, parca.length, ...parca.filter(Boolean));
  if (!temelMod()) yaz($("#oDagilimYazi"), parca.join(" · "));

  const ti = bagli.reduce((t, c) => t + c.hiz_indirme, 0), ty = bagli.reduce((t, c) => t + c.hiz_yukleme, 0);
  const [a, ab] = hizParca(ti), [y, yb] = hizParca(ty);
  yaz($("#oIndir"), a); yaz($("#oIndirB"), ab); yaz($("#oYukle"), y); yaz($("#oYukleB"), yb);
  const en = bagli.reduce((m, c) => c.hiz_indirme > (m ? m.hiz_indirme : 0) ? c : m, null);
  yaz($("#oEnCok"), en && ti > 1e6 ? `En çok: ${ad(en)}` : "Ağda kayda değer trafik yok");

  const h = v.hat || {};
  if (h.indirme_kbps) {
    yaz($("#oHat"), `${Math.round(h.indirme_kbps / 1000)} / ${Math.round(h.yukleme_kbps / 1000)} Mbps`);
    yaz($("#oHatAlt"), `${h.tur || "DSL"} · hat ${h.hat_durumu === "Up" ? "bağlı" : h.hat_durumu}`);
    yaz($("#oHatSure"), h.internet_baslangic ? `Son kesintiden beri ${sure(h.internet_baslangic)}` : "");
  } else {
    const internet = v.internet === "var" || h.baglanti === "Connected";
    yaz($("#oHat"), internet ? "Bağlı" : v.internet === "yok" ? "Kesik" : "—");
    yaz($("#oHatAlt"), temelMod() ? "her 15 sn'de bir bu bilgisayardan ölçülür" : ""); yaz($("#oHatSure"), "");
  }

  const ag = $("#oAglar");
  if (!yetenek("misafir") && !yetenek("wifi_zaman")) {
    // Wi-Fi ayarı olmayan modem: temel mod ya da Wi-Fi bölümü henüz yazılmamış bir sürücü
    const temel = temelMod(), deneysel = !!(v.surucu && v.surucu.deneysel), imza = temel ? "temel" : "modem" + deneysel;
    yaz($("#oAglarBaslik"), temel ? "Temel mod" : "Modem");
    if (ag.dataset.imza !== imza) {
      const k = el("div", "temel-kart");
      k.append(el("p", "", temel ? "Modem şifresi olmadan çalışıyor. Cihazlar ağ taranarak bulunur; uykudaki telefonlar görünmeyebilir."
        : deneysel ? "Bu modemin sürücüsü deneysel: henüz gerçek bir cihazda denenmedi. Bir sorun görürseniz GitHub'da bildirin."
        : "Wi-Fi ayarları (zamanlama, misafir ağı) bu modemde henüz desteklenmiyor."),
        dugme(temel ? "Modem bağlantısını değiştir" : "Modem bağlantısı", "", () => { S.kurulumZorla = true; S.kesif = null; ciz(S.veri); }));
      ag.replaceChildren(k);
      ag.dataset.imza = imza;
    }
    return;
  }
  yaz($("#oAglarBaslik"), "Wi-Fi ağları");
  const ekAg = S.modemAyar && S.modemAyar.ek_ag;
  const wz = S.modemAyar && S.modemAyar.wifi.some(w => w.zaman_acik);
  const satirlar = [["2,4 GHz", wz ? "Zamanlı" : "Ana ağ", true], ["5 GHz", wz ? "Zamanlı" : "Ana ağ", true],
    ["Misafir", ekAg ? (ekAg.acik ? ekAg.ssid : "Kapalı") : "—", !!(ekAg && ekAg.acik)]];
  const imza = JSON.stringify(satirlar);
  if (ag.dataset.imza !== imza) {
    ag.replaceChildren(...satirlar.map(([n, a, acik]) => {
      const s = el("div", "ag"), sol = el("div");
      sol.append(el("b", "", n), el("span", "", " · " + a));
      s.append(sol, el("span", "durum-hap" + (acik ? " acik" : ""), acik ? "Açık" : "Kapalı"));
      return s;
    }));
    ag.dataset.imza = imza;
  }
}

// --- trafik grafiği (SVG, kütüphanesiz) ---
function grafikCiz(veri) {
  const kutu = $("#grafik");
  if (!kutu) return;
  const G = kutu.clientWidth || 600, Y = kutu.clientHeight || 230, sol = 40, alt = 22, ust = 22;
  if (veri.length < 2) { kutu.innerHTML = '<div class="grafik-bos">Grafik birkaç saniye içinde dolmaya başlayacak…</div>'; return; }
  const t1 = veri[veri.length - 1][0], t0 = t1 - 1800;
  const noktalar = veri.filter(n => n[0] >= t0);
  const enYuksek = Math.max(1e6, ...noktalar.map(n => Math.max(n[1], n[2])));
  const adim = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000].find(a => a * 1e6 * 4 >= enYuksek) || 1000;
  const tavan = adim * 4 * 1e6;
  const x = t => sol + (t - t0) / 1800 * (G - sol - 4);
  const y = d => ust + (1 - d / tavan) * (Y - ust - alt);
  const yol = i => noktalar.map((n, k) => `${k ? "L" : "M"}${x(n[0]).toFixed(1)},${y(n[i]).toFixed(1)}`).join("");
  const indir = yol(1);
  const alan = `${indir}L${x(noktalar.at(-1)[0]).toFixed(1)},${y(0)}L${x(noktalar[0][0]).toFixed(1)},${y(0)}Z`;
  let eksen = "";
  for (let i = 0; i <= 4; i++) {
    const d = adim * i * 1e6, yy = y(d).toFixed(1);
    eksen += `<line class="eksen" x1="${sol}" x2="${G}" y1="${yy}" y2="${yy}"/><text class="etiket" x="${sol - 8}" y="${+yy + 4}" text-anchor="end">${adim * i}</text>`;
  }
  for (const dk of [30, 20, 10, 0]) {
    eksen += `<text class="etiket" x="${x(t1 - dk * 60)}" y="${Y - 4}" text-anchor="${dk === 30 ? "start" : dk === 0 ? "end" : "middle"}">${dk ? dk + " dk önce" : "şimdi"}</text>`;
  }
  const renk = getComputedStyle(document.documentElement).getPropertyValue("--vurgu").trim();
  kutu.innerHTML = `<svg viewBox="0 0 ${G} ${Y}" preserveAspectRatio="none">
    <defs><linearGradient id="dolgu" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${renk}" stop-opacity=".32"/><stop offset="1" stop-color="${renk}" stop-opacity="0"/></linearGradient></defs>
    ${eksen}<text class="etiket" x="0" y="10">Mbps</text>
    <path class="alan-indir" d="${alan}" fill="url(#dolgu)"/>
    <path class="cizgi-indir" d="${indir}"/><path class="cizgi-yukle" d="${yol(2)}"/></svg>`;
}
window.addEventListener("resize", () => S.veri && grafikCiz(S.veri.trafik || []));

function enlerCiz(bagli) {
  const liste = [...bagli].sort((a, b) => b.hiz_indirme - a.hiz_indirme).filter(c => c.hiz_indirme >= 2000).slice(0, 5);
  const kutu = $("#enler");
  if (!liste.length) { if (!kutu.querySelector(".bos")) kutu.replaceChildren(el("div", "bos", "Şu an hiçbir cihaz kayda değer veri kullanmıyor.")); return; }
  const tepe = liste[0].hiz_indirme;
  const imza = liste.map(c => c.mac).join();
  if (kutu.dataset.imza !== imza) {
    kutu.replaceChildren(...liste.map(c => {
      const s = el("div", "en"); s.dataset.mac = c.mac;
      const cb = el("div", "cubuk"); cb.append(el("i"));
      s.append(el("b"), el("span", "mono"), cb);
      return s;
    }));
    kutu.dataset.imza = imza;
  }
  liste.forEach((c, i) => {
    const s = kutu.children[i];
    yaz(s.children[0], ad(c)); yaz(s.children[1], hiz(c.hiz_indirme));
    s.querySelector("i").style.width = Math.max(3, c.hiz_indirme / tepe * 100) + "%";
  });
}

// --- cihaz tablosu ---
function tabloCiz(kutu, liste, surukle) {
  if (!kutu.querySelector(".baslik-satir")) {
    const b = el("div", "satir baslik-satir");
    ["", "Cihaz", "Bağlantı", "IP adresi", "Durum", "Şu an", "Toplam", "Bağlantı hızı"].forEach(t => b.append(el("div", "", t)));
    kutu.append(b);
  }
  let bos = kutu.querySelector(".tablo-bos");
  if (!liste.length) {
    if (!bos) kutu.append(bos = el("div", "tablo-bos"));
    yaz(bos, S.arama ? "Aramaya uyan cihaz yok." : "Burada gösterilecek cihaz yok.");
  } else if (bos) bos.remove();

  const mevcut = new Map($$(".satir[data-mac]", kutu).map(s => [s.dataset.mac, s]));
  const istenen = new Set(liste.map(c => c.mac));
  mevcut.forEach((s, mac) => { if (!istenen.has(mac)) { s.remove(); mevcut.delete(mac); } });
  let onceki = kutu.querySelector(".baslik-satir");
  for (const c of liste) {
    let s = mevcut.get(c.mac);
    if (!s) s = satirYap(c, kutu);
    satirGuncelle(s, c, surukle);
    if (onceki.nextElementSibling !== s) onceki.after(s);
    onceki = s;
  }
}

function satirYap(c, kutu) {
  const s = el("div", "satir");
  s.dataset.mac = c.mac;
  const tut = el("div", "tutamac"); tut.title = "Sürükleyerek sırala"; tut.append(svgKullan("i-tutamac"));
  const adK = el("div", "c-ad"), simge = el("div", "c-simge"), metin = el("div", "c-metin");
  metin.append(el("b"), el("small"));
  adK.append(simge, metin);
  s.append(tut, adK, el("span", "hap"), el("span", "c-soluk mono"), el("div", "etiketler"), el("span", "c-sayi"), el("span", "c-sayi"), el("span", "c-soluk"));
  s.onclick = e => { if (!e.target.closest(".tutamac")) cekmeceAc(s.dataset.mac); };
  // sürükle-bırak: yalnız tutamaçtan
  tut.onmousedown = () => s.draggable = s.dataset.surukle === "1";
  s.addEventListener("dragstart", e => { S.surukle = s; s.classList.add("surukleniyor"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", s.dataset.mac); });
  s.addEventListener("dragend", () => { s.classList.remove("surukleniyor"); s.draggable = false; $$(".hedef-ust").forEach(x => x.classList.remove("hedef-ust")); S.surukle = null; });
  s.addEventListener("dragover", e => {
    if (!S.surukle || S.surukle === s || S.surukle.parentElement !== s.parentElement) return;
    e.preventDefault();
    $$(".hedef-ust", kutu).forEach(x => x.classList.remove("hedef-ust"));
    s.classList.add("hedef-ust");
  });
  s.addEventListener("drop", e => {
    e.preventDefault();
    const tasinan = S.surukle;
    if (!tasinan || tasinan === s) return;
    s.before(tasinan);
    tasinan.animate([{ transform: "scale(.98)", opacity: .6 }, { transform: "none", opacity: 1 }], { duration: 260, easing: "cubic-bezier(.2,.7,.2,1)" });
    siraKaydet(kutu);
  });
  return s;
}

function satirGuncelle(s, c, surukle) {
  s.dataset.surukle = surukle ? "1" : "0";
  s.children[0].style.visibility = surukle ? "" : "hidden";
  s.classList.toggle("cevrimdisi", !c.aktif);
  s.classList.toggle("yeni", c.yeni);
  s.classList.toggle("adsiz", !c.ad && !c.host_adi);
  s.classList.toggle("engelli", c.engelli);
  const simge = s.querySelector(".c-simge"), t = tur(c);
  if (simge.dataset.tur !== t) { simge.replaceChildren(svgKullan("i-" + t)); simge.dataset.tur = t; }
  yaz(s.querySelector(".c-metin b"), ad(c));
  yaz(s.querySelector(".c-metin small"), [c.bu_pc ? "Bu bilgisayar" : c.ad && c.host_adi && c.ad !== c.host_adi ? c.host_adi : "",
    c.grup, c.uretici || (c.rastgele ? "Gizli MAC" : ""), !c.host_adi && !c.uretici ? c.mac.slice(-8) : ""].filter(Boolean).join(" · ") || c.mac);
  const hap = s.children[2];
  yaz(hap, bantYazi(c)); hap.className = "hap " + bantSinif(c);
  yaz(s.children[3], c.ip || "—");
  const et = [];
  if (c.engelli) et.push(["engel", "Engelli"]);
  if (c.durduruldu) et.push(["engel", "İnternet durduruldu"]);
  else if (c.takvimli && yetenek("durdur")) et.push(["", "Takvimli"]);
  if (c.yeni) et.push(["yeni", "Yeni"]);
  if (c.sinir) et.push(["sinir", `${sayi(c.sinir, c.sinir % 1 ? 1 : 0)} Mbps sınır`]);
  if (c.sabit_ip) et.push(["sabit", "Sabit IP"]);
  const kutu = s.children[4], imza = et.map(e => e[1]).join("|");
  if (kutu.dataset.imza !== imza) { kutu.replaceChildren(...et.map(([k, m]) => el("span", "etiket " + k, m))); kutu.dataset.imza = imza; }
  const h = s.children[5];
  yaz(h, c.aktif ? hiz(c.hiz_indirme) : "—");
  h.classList.toggle("bosta", !c.aktif || c.hiz_indirme < 2000);
  h.classList.toggle("akiyor", c.hiz_indirme >= 1e6);
  yaz(s.children[6], c.aktif || c.indirilen ? bayt(c.indirilen) : "—");
  yaz(s.children[7], c.aktif ? (c.tur === "wifi" && c.baglanti ? c.baglanti + " Mbps" : "—") : (c.son ? gun(c.son) : "—"));
}

function siraKaydet(kutu) {
  const gorunen = $$(".satir[data-mac]", kutu).map(s => s.dataset.mac);
  const eski = (S.veri.ayar && S.veri.ayar.sira) || [];
  const yeni = [...gorunen, ...eski.filter(m => !gorunen.includes(m))];
  S.veri.ayar = { ...(S.veri.ayar || {}), sira: yeni };
  api("/api/ayar", { sira: yeni }).catch(e => goster(e.message, true));
}

// ---------- cihaz çekmecesi ----------
const cihaz = mac => S.veri && S.veri.cihazlar.find(c => c.mac === mac);
function cekmeceAc(mac) {
  S.cekmece = mac;
  const k = $("#cekmece");
  k.replaceChildren();
  k.hidden = false;
  cekmeceCiz(mac, true);
}
function cekmeceKapat() { S.cekmece = null; $("#cekmece").hidden = true; }
document.addEventListener("mousedown", e => {
  if (S.cekmece && !e.target.closest("#cekmece, .satir, .perde, .bildirim")) cekmeceKapat();
});

function cekmeceCiz(mac, ilk) {
  const c = cihaz(mac), k = $("#cekmece");
  if (!c) return cekmeceKapat();
  if (ilk || !k.firstChild) {
    const ust = el("div", "cek-ust"), simge = el("div", "c-simge"), adK = el("div", "cek-ad");
    simge.append(svgKullan("i-" + tur(c)));
    const girdi = el("input");
    girdi.value = c.ad || c.host_adi || "";
    girdi.placeholder = "Ad verin, örn. Ahmet'in telefonu";
    girdi.maxLength = 40;
    girdi.onkeydown = e => { if (e.key === "Enter") girdi.blur(); if (e.key === "Escape") { girdi.value = c.ad || c.host_adi || ""; girdi.blur(); } };
    girdi.onblur = async () => {
      const yeni = girdi.value.trim(), x = cihaz(mac);
      if (yeni === (x.ad || x.host_adi || "")) return;
      try { await api("/api/islem", { islem: "adlandir", mac, ad: yeni === x.host_adi ? "" : yeni }); goster("Ad kaydedildi."); tazele(); }
      catch (e) { goster(e.message, true); }
    };
    adK.append(girdi, el("small", "cek-alt"));
    const kapat = el("button", "kapat-dugme"); kapat.append(svgKullan("i-kapat")); kapat.onclick = cekmeceKapat;
    ust.append(simge, adK, kapat);
    k.append(ust, el("div", "bilgiler"), el("div", "cek-islemler"), cekmeceMeta(c), el("div", "cek-bolum cek-gecmis"));
    cihazGecmisi(mac);
  }
  yaz(k.querySelector(".cek-alt"), [bantYazi(c), c.bu_pc && "bu bilgisayar", c.host_adi && c.ad && c.host_adi !== c.ad && c.host_adi].filter(Boolean).join(" · "));
  const bilgiler = [
    ["IP adresi", c.ip || "—", true], ["MAC adresi", c.mac, true],
    ["Şu an", c.aktif ? hiz(c.hiz_indirme) : "—"], ["Toplam indirme", bayt(c.indirilen)],
    ["Bağlantı hızı", c.aktif && c.baglanti ? c.baglanti + " Mbps" : "—"], ["Toplam yükleme", bayt(c.yuklenen)],
    ["İlk görülme", c.ilk ? gun(c.ilk) : "—"], ["Son görülme", c.aktif ? "şu an bağlı" : c.son ? gun(c.son) : "—"],
    ["Üretici", c.uretici || (c.rastgele ? "Gizli MAC (telefonun gizlilik ayarı)" : "Bilinmiyor"), false, true],
  ].filter(([n]) => yetenek("sayac") || !["Şu an", "Toplam indirme", "Bağlantı hızı", "Toplam yükleme"].includes(n));
  const b = k.querySelector(".bilgiler");
  if (b.children.length !== bilgiler.length) b.replaceChildren(...bilgiler.map(([n, , mono, genis]) => { const d = el("div", "bilgi" + (genis ? " genis" : "")); d.append(el("small", "", n), el("b", mono ? "mono" : "")); return d; }));
  bilgiler.forEach(([, v], i) => yaz(b.children[i].querySelector("b"), v));

  const yuvaDolu = !!S.veri.durdur_yuva && (S.veri.durdurulan || []).length >= S.veri.durdur_yuva;
  const islemler = [
    c.durduruldu ? ["devam", "İnterneti devam ettir", "Cihaz yeniden internete çıkabilir", "Durduruldu", false]
      : ["durdur", "İnterneti durdur", c.bu_pc ? "Bu bilgisayarın interneti durdurulamaz"
        : yuvaDolu ? `Modem aynı anda en fazla ${S.veri.durdur_yuva} cihazı durdurabiliyor; önce birini devam ettirin`
        : "Wi-Fi'de kalır ama internete çıkamaz; kablolu cihazlarda da çalışır", "", c.bu_pc || yuvaDolu],
    ["sinir", "Hız sınırı", "Bu cihazın internet hızını sınırla", c.sinir ? `${sayi(c.sinir, c.sinir % 1 ? 1 : 0)} Mbps` : "Yok", false],
    ["sabit", "Sabit IP", "Her bağlandığında aynı adresi alsın", c.sabit_ip || "Yok", false],
    c.engelli ? ["engel_kaldir", "Engeli kaldır", "Cihaz yeniden Wi-Fi'ye bağlanabilir", "", false]
      : ["engelle", "Engelle", c.tur === "kablo" ? "Kabloyla bağlı cihazlar Wi-Fi filtresiyle engellenemez" : "Wi-Fi'ye bağlanamasın", "", c.tur === "kablo"],
  ];
  const gerek = { durdur: "durdur", devam: "durdur", sinir: "sinir", sabit: "sabit_ip", engelle: "engelle", engel_kaldir: "engelle" };
  islemler.splice(0, islemler.length, ...islemler.filter(i => yetenek(gerek[i[0]])));
  const kutu = k.querySelector(".cek-islemler"), imza = JSON.stringify(islemler) + S.mesgul;
  if (kutu.dataset.imza !== imza) {
    if (!islemler.length) {
      kutu.replaceChildren(el("p", "bilgi-not", "Temel modda WaveSnap cihazları yalnız görür; engelleme, durdurma ve hız sınırı için modemin WaveSnap'e şifresiyle bağlanması gerekir. Modeminiz desteklenmiyorsa bu özellikler yoktur."));
      kutu.dataset.imza = imza;
      return;
    }
    kutu.replaceChildren(...islemler.map(([is, baslik, aciklama, deger, kapali]) => {
      const d = el("button", "cek-islem" + (is === "engelle" ? " tehlike" : "")), sol = el("div");
      sol.append(el("b", "", baslik), el("small", "", aciklama));
      d.append(sol, el("span", "deger", deger));
      d.disabled = kapali || S.mesgul;
      d.onclick = () => is === "engel_kaldir" ? calistir("engel_kaldir", mac, {}, `${ad(c)} için engel kaldırılıyor…`)
        : is === "durdur" ? calistir("durdur", mac, {}, `${ad(c)} için internet durduruluyor…`)
        : is === "devam" ? calistir("devam", mac, {}, `${ad(c)} için internet açılıyor…`)
        : islemPenceresi(is, mac);
      return d;
    }));
    kutu.dataset.imza = imza;
  }
}

// ---------- işlem pencereleri ----------
function pencereAc(icerik) {
  $("#pencere").replaceChildren(...icerik);
  $("#perde").hidden = false;
  const ilk = $("#pencere").querySelector("input, .dugme.ana");
  if (ilk) setTimeout(() => ilk.focus(), 30);
}
function pencereKapat() { if (!S.mesgul) $("#perde").hidden = true; }
$("#perde").addEventListener("mousedown", e => { if (e.target.id === "perde") pencereKapat(); });
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if (!$("#perde").hidden) pencereKapat(); else if (S.cekmece && document.activeElement.tagName !== "INPUT") cekmeceKapat();
});
const altSatir = (...d) => { const x = el("div", "pencere-alt"); x.append(...d); return x; };
const dugme = (m, s, is) => { const b = el("button", "dugme " + (s || ""), m); b.onclick = is; return b; };
const vazgec = () => dugme("Vazgeç", "hafif", pencereKapat);

function islemPenceresi(is, mac) {
  const c = cihaz(mac);
  if (!c) return;
  const a = ad(c);
  if (is === "sinir") {
    const sec = el("div", "secenekler");
    SINIRLAR.forEach(m => {
      const b = dugme("", c.sinir === m ? "secili" : "", () => calistir("sinir", mac, { mbps: m }, `${a} için ${m} Mbps sınır konuyor…`));
      b.append(String(m), el("small", "", "Mbps"));
      sec.append(b);
    });
    pencereAc([el("h3", "", `${a} için hız sınırı`),
      el("p", "", "İndirme ve yükleme seçtiğiniz hızla sınırlanır. Bağlantı kopmaz, hemen uygulanır." + (c.aktif && c.hiz_indirme >= 2000 ? ` Şu an ${hiz(c.hiz_indirme)} kullanıyor.` : "")),
      sec, el("p", "not", "Modem en fazla 18 cihaza ayrı sınır koyabilir. Akıcı video için 5 Mbps genelde yeterlidir."),
      altSatir(...(c.sinir ? [dugme("Sınırı kaldır", "sol", () => calistir("sinir_kaldir", mac, {}, `${a} için sınır kaldırılıyor…`))] : []), vazgec())]);
  } else if (is === "sabit") {
    const girdi = el("input", "mono"); girdi.value = c.sabit_ip || c.ip;
    const kaydet = () => calistir("sabit", mac, { ip: girdi.value.trim() }, `${a} için IP sabitleniyor…`);
    girdi.onkeydown = e => { if (e.key === "Enter") kaydet(); };
    pencereAc([el("h3", "", `${a} için sabit IP`),
      el("p", "", "Bu cihaz modeme her bağlandığında hep aynı adresi alır. Yazıcı, kamera ya da kasa bilgisayarı için kullanışlıdır."),
      girdi, el("p", "not", "Değişiklik cihaz bir sonraki bağlanışında geçerli olur."),
      altSatir(...(c.sabit_ip ? [dugme("Sabit IP'yi kaldır", "sol", () => calistir("sabit_kaldir", mac, {}, "Sabit IP kaldırılıyor…"))] : []),
        vazgec(), dugme(c.sabit_ip ? "Güncelle" : "Sabitle", "ana", kaydet))]);
  } else if (is === "engelle") {
    const p = [el("h3", "", `${a} engellensin mi?`),
      el("p", "", "Bu cihaz 2,4 ve 5 GHz Wi-Fi ağlarına bağlanamaz" + (c.aktif ? " ve şu anki bağlantısı kesilir" : "") + ". Engeli istediğiniz an kaldırabilirsiniz.")];
    if (!S.veri.filtre_acik) p.push(el("p", "dikkat", "İlk engellemede modem Wi-Fi filtresini açmak için kablosuz ağı yeniden başlatır. Bağlı cihazlarda yaklaşık 30 saniyelik kesinti olabilir; sonraki engellemelerde filtre zaten açık olur."));
    if (c.rastgele) p.push(el("p", "not", "Bu cihaz gizli (rastgele) MAC adresi kullanıyor. Ağı unutup yeniden bağlanırsa farklı bir adresle gelebilir."));
    p.push(altSatir(vazgec(), dugme("Engelle", "ana tehlike", () => calistir("engelle", mac, {}, `${a} engelleniyor…`))));
    pencereAc(p);
  }
}

async function calistir(islem, mac, ekVeri, yazi) {
  if (S.mesgul) return;
  S.mesgul = true;
  const sayac = el("span"), surec = el("div", "surec");
  surec.append(el("span", "donen"), el("span", "", yazi + " "), sayac);
  pencereAc([el("h3", "", "Modeme yazılıyor"), surec, el("p", "not", "Modem ayarı kaydederken bekleyin. Wi-Fi ayarlarında bu 30 saniyeyi bulabilir.")]);
  const t0 = Date.now(), zaman = setInterval(() => sayac.textContent = Math.round((Date.now() - t0) / 1000) + " sn", 500);
  try {
    const r = await api("/api/islem", { islem, mac, ...ekVeri });
    const sn = Math.round((Date.now() - t0) / 1000);
    S.mesgul = false; pencereKapat();
    goster(r.sonuc + (sn >= 3 ? ` (${sn} sn)` : ""));
    ciz(r);
  } catch (e) { S.mesgul = false; pencereKapat(); goster(e.message, true); tazele(); }
  finally { clearInterval(zaman); S.mesgul = false; }
}

let bildirimZaman;
function goster(metin, kotu) {
  const b = $("#bildirim");
  b.hidden = true; b.className = "bildirim" + (kotu ? " kotu" : ""); b.textContent = metin;
  void b.offsetWidth; b.hidden = false;
  clearTimeout(bildirimZaman);
  bildirimZaman = setTimeout(() => b.hidden = true, kotu ? 9000 : 5000);
}

// ---------- ayarlar ----------
$("#bildirimAnahtar").onclick = async e => {
  const acik = !e.currentTarget.classList.contains("acik");
  e.currentTarget.classList.toggle("acik", acik);
  try { ciz(await api("/api/ayar", { bildirim: acik })); } catch (x) { goster(x.message, true); }
};
$("#birak").onclick = async () => { ciz(await api("/api/duraklat", { dakika: 10 })); };
$("#sifreAc").onclick = () => { S.kurulumZorla = true; S.kesif = null; ciz(S.veri); };
async function kesifYap() {
  S.kesif = { bekliyor: true };
  const k = $("#kKesif");
  k.className = "kurulum-kesif"; k.replaceChildren(el("span", "donen"), el("span", "", "Modem aranıyor…"));
  let r;
  try { r = await api("/api/kesif"); } catch (e) { r = { adres: "192.168.1.1", surucu: "genel", tanindi: false, secenekler: [] }; }
  S.kesif = r;
  const sec = $("#kSurucu");
  sec.replaceChildren(...(r.secenekler || []).map(o => new Option(t(o.ad) + (o.kimlik === r.surucu && r.tanindi ? " · " + t("tanındı") : ""), o.kimlik)));
  sec.value = (S.veri && S.veri.kurulu && r.mevcut) || r.surucu;
  $("#kAdres").value = (S.veri && S.veri.kurulu && S.veri.modem_adres) || r.adres;
  k.classList.toggle("tanindi", r.tanindi);
  k.replaceChildren(el("span", "", r.tanindi
    ? `${r.model || t(r.surucu_ad)} bulundu (${r.adres}). WaveSnap bu modemi tam kontrol edebilir.`
    : `${r.model || "Modem"} (${r.adres}) bu sürümde tanınmadı. Temel modda kullanabilirsiniz; yine de denemek isterseniz türünü seçin.`));
  kurulumTuruGoster();
}
function kurulumTuruGoster() {
  const o = ((S.kesif && S.kesif.secenekler) || []).find(x => x.kimlik === $("#kSurucu").value);
  const giris = !o || o.giris;
  $("#kGiris").hidden = !giris;
  $("#kTemelNot").hidden = giris;
  $("#kKilitNot").hidden = !giris || $("#kSurucu").value !== "tplink_cgi";
  $("#kSurucuNot").hidden = !(o && o.not);
  if (o && o.not) yaz($("#kSurucuNot"), o.not);
  const kul = $("#kKullanici");
  if (o && giris && !kul.dataset.elle) kul.value = o.kullanici;
  yaz($("#kDugme"), giris ? "Kaydet ve bağlan" : "Temel modda başla");
}
$("#kSurucu").onchange = kurulumTuruGoster;
$("#kKullanici").oninput = e => { e.target.dataset.elle = "1"; };
$("#kVazgec").onclick = () => { S.kurulumZorla = false; ciz(S.veri); };
$("#kapat").onclick = async () => { await api("/api/kapat", {}).catch(() => {}); window.close(); };
$("#kurulumForm").onsubmit = async e => {
  e.preventDefault();
  const dg = $("#kDugme"), hata = $("#kurulumHata");
  dg.disabled = true; dg.textContent = "Deneniyor…"; hata.hidden = true;
  try {
    await api("/api/kurulum", { surucu: $("#kSurucu").value, adres: $("#kAdres").value.trim(),
      kullanici: $("#kKullanici").value, sifre: $("#kSifre").value });
    $("#kSifre").value = ""; S.kurulumZorla = false; S.kesif = null; S.modemAyar = null;
    goster("Modem bağlantısı kaydedildi."); setTimeout(tazele, 800);
    api("/api/modem-ayar").then(m => { S.modemAyar = m; }).catch(() => {});
  } catch (err) { hata.textContent = err.message; hata.hidden = false; }
  finally { dg.disabled = false; kurulumTuruGoster(); }
};

// ---------- çekmece: tür, grup, not, güvenilir ----------
function cekmeceMeta(c) {
  const mac = c.mac, kutu = el("div", "cek-bolum");
  const kaydet = async alanlar => {
    try { await api("/api/islem", { islem: "meta", mac, ...alanlar }); tazele(); }
    catch (e) { goster(e.message, true); }
  };
  const secim = el("div", "cins-secim");
  CINSLER.forEach(([k, m]) => {
    const b = el("button", c.cins === k ? "secili" : "");
    b.append(svgKullan("i-" + k), m);
    b.onclick = () => { $$("button", secim).forEach(x => x.classList.toggle("secili", x === b)); kaydet({ cins: k }); };
    secim.append(b);
  });
  const grup = el("input");
  grup.value = c.grup; grup.placeholder = "Örn. Personel, Kasa, Müşteri"; grup.maxLength = 30;
  const liste = el("datalist");
  liste.id = "grupListe";
  [...new Set(S.veri.cihazlar.map(x => x.grup).filter(Boolean))].forEach(g => liste.append(new Option(g)));
  grup.setAttribute("list", "grupListe");
  grup.onchange = () => kaydet({ grup: grup.value.trim() });
  const not = el("textarea");
  not.value = c.not; not.placeholder = "Bu cihazla ilgili not"; not.maxLength = 300;
  not.onchange = () => kaydet({ not: not.value });
  const guven = el("div", "anahtar-satir"), gm = el("div", "", "Güvenilir cihaz");
  gm.append(el("small", "", "Tanıdığınız cihazları işaretleyin; toplu engelleme bunlara dokunmaz."));
  const ga = el("button", "anahtar" + (c.guvenilir ? " acik" : ""));
  ga.onclick = () => { ga.classList.toggle("acik"); kaydet({ guvenilir: ga.classList.contains("acik") }); };
  guven.append(gm, ga);
  const l1 = el("label", "alan", "Grup"), l2 = el("label", "alan", "Not");
  l1.append(grup, liste);
  l2.append(not);
  const ara = el("div");
  ara.style.height = "14px";
  kutu.append(el("b", "", "Cihaz türü"), secim, ara, l1, l2, guven);
  return kutu;
}

async function cihazGecmisi(mac) {
  let g;
  try { g = await api("/api/cihaz-gecmisi?mac=" + encodeURIComponent(mac)); } catch (e) { return; }
  const kutu = $("#cekmece .cek-gecmis");
  if (!kutu || S.cekmece !== mac) return;
  const toplam = g.gunluk.reduce((t, d) => t + d.indirme + d.yukleme, 0);
  const grafik = el("div", "grafik mini-grafik");
  if (yetenek("sayac")) {  // modem cihaz başına trafik saymıyorsa kullanım grafiği yok, yalnız olaylar
    kutu.replaceChildren(el("b", "", `Son 30 gün · ${bayt(toplam)}`), grafik);
    if (g.gunluk.length) cubukGrafik(grafik, g.gunluk, "gun");
    else grafik.append(el("div", "grafik-bos", "Henüz kayıt yok"));
  } else kutu.replaceChildren();
  if (g.olaylar.length) {
    const ol = el("div", "olaylar");
    ol.style.maxHeight = "200px"; ol.style.marginTop = "10px";
    kutu.append(ol);
    olayListesi(ol, g.olaylar, o => [{ geldi: "Bağlandı", gitti: "Ayrıldı", yeni: "İlk kez bağlandı" }[o.tur] || o.tur, o.ayrinti], "");
  }
}

// ---------- tanınmayanları toplu engelle ----------
$("#topluEngel").onclick = () => {
  const adaylar = S.veri.cihazlar.filter(c => c.aktif && c.tur === "wifi" && !c.engelli && !c.guvenilir && !c.ad && !c.bu_pc);
  if (!adaylar.length) return goster("Engellenecek tanınmayan Wi-Fi cihazı yok. Adı olan ya da güvenilir işaretli cihazlar listeye girmez.");
  const liste = el("div", "secim-liste"), kutular = [];
  adaylar.forEach(c => {
    const l = el("label"), k = el("input");
    k.type = "checkbox"; k.checked = true; k.value = c.mac;
    l.append(k, ad(c), el("small", "", c.ip + " · " + c.mac.slice(-8)));
    liste.append(l); kutular.push(k);
  });
  const uyari = S.veri.filtre_acik ? [] : [el("p", "dikkat", "İlk engellemede modem Wi-Fi'yi yeniden başlatır; yaklaşık 30 saniyelik kesinti olabilir.")];
  pencereAc([el("h3", "", "Tanınmayanları engelle"),
    el("p", "", "Adı olmayan ve güvenilir işaretlenmemiş bağlı Wi-Fi cihazları. Engellemek istemediklerinizin işaretini kaldırın."), liste, ...uyari,
    altSatir(vazgec(), dugme("Seçilenleri engelle", "ana tehlike", async () => {
      const secili = kutular.filter(k => k.checked).map(k => k.value);
      for (let i = 0; i < secili.length; i++) {
        await calistir("engelle", secili[i], {}, `${i + 1}/${secili.length}: ${ad(cihaz(secili[i]))} engelleniyor…`);
      }
    }))]);
};

async function dilYukle() {
  // ilk kurulumda İngilizce; sonra Ayarlar'dan seçilen dil (sunucuda saklanır, tarayıcıda da önbellek)
  let dil = "en";
  try { dil = localStorage.getItem("ws-dil") || dil; } catch (e) {}
  try { const v = await api("/api/durum"); if (v.ayar && v.ayar.dil) dil = v.ayar.dil; S.ilkVeri = v; } catch (e) {}
  let sozluk = null;
  if (dil !== "tr") { try { sozluk = await fetch(`dil/${dil}.json`, { cache: "no-store" }).then(r => r.json()); } catch (e) { dil = "tr"; } }
  try { localStorage.setItem("ws-dil", dil); } catch (e) {}
  ceviriBaslat(dil, sozluk);
  let diller = [["en", "English", "us"], ["tr", "Türkçe", "tr"]];
  try { diller = await api("/api/diller"); } catch (e) {}
  $("#dilSecim").replaceChildren(...diller.map(([kod, ad, bayrak]) => {
    const b = el("button", kod === dil ? "secili" : "");
    const resim = el("img", "bayrak");
    resim.src = `bayrak/${bayrak}.svg`; resim.alt = "";
    const yazi = el("span", "dil-ad", ad);
    yazi.dataset.ham = "";  // dil adları her zaman kendi dilinde yazılır
    b.append(resim, yazi, el("span", "tik", "✓"));
    b.onclick = async () => {
      if (kod === dil) return;
      try { await api("/api/ayar", { dil: kod }); localStorage.setItem("ws-dil", kod); } catch (e) {}
      location.reload();
    };
    return b;
  }));
}

window.addEventListener("DOMContentLoaded", async () => {
  try { await dilYukle(); } finally { document.documentElement.classList.remove("hazirlaniyor"); }
  temaUygula(document.documentElement.dataset.tema);
  sayfaAc(location.hash.slice(1) || "genel");
  if (S.ilkVeri) { try { ciz(S.ilkVeri); } catch (e) { console.error(e); } }
  await tazele();
  setInterval(tazele, 2000);
  api("/api/modem-ayar").then(m => { S.modemAyar = m; }).catch(() => {});
});


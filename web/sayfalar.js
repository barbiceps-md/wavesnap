"use strict";
/* Geçmiş, Zamanlama, Misafir ağı ve Araçlar sayfaları. app.js'teki yardımcıları (el, yaz, api, S, ...) kullanır. */

const GUN_KISA = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];
// Ebeveyn denetiminde takvimin anlamı (telefonla yapılan denemeyle kesinleşir)
const EBEVEYN = { kip: 0, secili: "İnternet kapalı", bos: "İnternet açık" };

const macAd = mac => { const c = cihaz(mac); return c ? ad(c) : mac; };
const saatYaz = ts => new Date(ts * 1000).toLocaleTimeString(YEREL(), { hour: "2-digit", minute: "2-digit" });
function gunBaslik(ts) {
  const d = new Date(ts * 1000), bugun = new Date();
  const fark = Math.round((new Date(bugun.getFullYear(), bugun.getMonth(), bugun.getDate()) - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 864e5);
  return fark === 0 ? "Bugün" : fark === 1 ? "Dün" : d.toLocaleDateString(YEREL(), { weekday: "long", day: "numeric", month: "long" });
}
function dkYaz(sn) {
  const dk = Math.max(1, Math.round(sn / 60));
  return dk < 60 ? `${dk} dk` : `${Math.floor(dk / 60)} sa ${dk % 60} dk`;
}
function kutuBaslik(kutu, baslik, aciklama, sag) {
  const ust = el("div", "baslik-satir2"), sol = el("div");
  sol.append(el("h3", "", baslik));
  if (aciklama) sol.append(el("p", "kutu-aciklama", aciklama));
  ust.append(sol);
  if (sag) ust.append(sag);
  kutu.append(ust);
}
function anahtar(acik, degisti) {
  const b = el("button", "anahtar" + (acik ? " acik" : ""));
  b.onclick = () => { b.classList.toggle("acik"); degisti && degisti(b.classList.contains("acik")); };
  b.deger = () => b.classList.contains("acik");
  return b;
}

// ---------- sayfa açılınca veri yükle ----------
function sayfaYukle(ad) {
  if (ad === "gecmis") gecmisYukle();
  if (ad === "zamanlama" || ad === "misafir") modemAyarYukle();
  if (ad === "araclar") { araclarCiz(); if (yetenek("kayitlar")) kayitYukle(); hizGecmisiYukle(); }
}

// =============================== GEÇMİŞ ===============================
S.gun = 7;
$$("#donem button").forEach(b => b.onclick = () => {
  S.gun = +b.dataset.gun;
  $$("#donem button").forEach(x => x.classList.toggle("secili", x === b));
  $("#kullanimCsv").href = `/api/disa-aktar?tur=kullanim&gun=${S.gun}`;
  gecmisYukle();
});
async function gecmisYukle() {
  let g;
  try { g = await api(`/api/gecmis?gun=${S.gun}`); } catch (e) { return goster(e.message, true); }
  S.gecmis = g;
  const ti = g.cihaz.reduce((t, c) => t + c.indirme, 0), ty = g.cihaz.reduce((t, c) => t + c.yukleme, 0);
  yaz($("#gToplam"), bayt(ti + ty));
  yaz($("#gToplamAlt"), `${bayt(ti)} indirme · ${bayt(ty)} yükleme`);
  const bas = Date.now() / 1000 - S.gun * 86400;
  const kes = g.kesintiler.filter(k => k.baslangic >= bas);
  const ksure = kes.reduce((t, k) => t + ((k.bitis || Date.now() / 1000) - k.baslangic), 0);
  yaz($("#gKesinti"), String(kes.length));
  yaz($("#gKesintiAlt"), kes.length ? `toplam ${dkYaz(ksure)} internetsiz` : "Bu dönemde kesinti kaydedilmedi");
  const h = g.hiz_testleri[0];
  yaz($("#gHiz"), h ? sayi(h.indirme, 0) : "—");
  yaz($("#gHizAlt"), h ? `↑ ${sayi(h.yukleme, 0)} Mbps · ${sayi(h.gecikme, 0)} ms · ${gun(h.zaman)}` : "Araçlar sayfasından test yapabilirsiniz");
  yaz($("#gGrafikAlt"), g.dilim_tur === "saat" ? "saat saat, son 24 saat" : "gün gün");
  cubukGrafik($("#gGrafik"), g.dilim, g.dilim_tur);

  const enler = $("#gEnler");
  const liste = g.cihaz.slice(0, 8), tepe = liste.length ? liste[0].indirme + liste[0].yukleme : 1, toplam = ti + ty || 1;
  enler.replaceChildren(...(liste.length ? liste.map((c, i) => {
    const s = el("div", "en"), cb = el("div", "cubuk"), cubuk = el("i");
    cubuk.style.width = Math.max(3, (c.indirme + c.yukleme) / tepe * 100) + "%";
    cb.append(cubuk);
    s.append(el("b", "", macAd(c.mac)), el("span", "mono", `${bayt(c.indirme + c.yukleme)} · ${yuzde((c.indirme + c.yukleme) / toplam * 100)}`), cb);
    return s;
  }) : [el("div", "bos", "Henüz kayıt yok. WaveSnap açık kaldıkça burası dolacak.")]));

  olayListesi($("#gOlaylar"), g.olaylar.filter(o => o.zaman >= bas), o => {
    const ne = { geldi: "bağlandı", gitti: "ayrıldı", yeni: "ilk kez bağlandı", yeniden_baglandi: "",
      durduruldu: "interneti durduruldu", devam: "interneti yeniden açıldı" }[o.tur] || o.tur;
    return o.tur === "yeniden_baglandi" ? ["İnternet bağlantısı yeniden kuruldu", "modem"] : [macAd(o.mac), ne + (o.ayrinti ? " · " + o.ayrinti : "")];
  }, "Bu dönemde olay yok.");
  olayListesi($("#gKesintiler"), kes.map(k => ({ zaman: k.baslangic, tur: "kesinti", k })), o => [
    `${o.k.tur === "internet" ? "İnternet kesildi" : "Ağ bağlantısı koptu"}`,
    o.k.bitis ? `${saatYaz(o.k.bitis)}'de geldi · ${dkYaz(o.k.bitis - o.k.baslangic)}` : "hâlâ sürüyor"], "Kesinti yok. WaveSnap açıkken her 15 saniyede bir kontrol ediliyor.");
}
function olayListesi(kutu, olaylar, metin, bos) {
  if (!olaylar.length) { kutu.replaceChildren(el("div", "bos-yazi", bos)); return; }
  const parcalar = [];
  let sonGun = "";
  for (const o of olaylar.slice(0, 250)) {
    const g = gunBaslik(o.zaman);
    if (g !== sonGun) { parcalar.push(el("div", "gun-baslik", g)); sonGun = g; }
    const [ana, alt] = metin(o), s = el("div", "olay " + o.tur), m = el("div");
    m.append(ana, el("small", "", alt));
    s.append(el("time", "", saatYaz(o.zaman)), el("i"), m);
    parcalar.push(s);
  }
  kutu.replaceChildren(...parcalar);
}
function cubukGrafik(kutu, dilim, tur) {
  const G = kutu.clientWidth || 600, Y = kutu.clientHeight || 230, sol = 46, alt = 22, ust = 22;
  if (!dilim.length) { kutu.innerHTML = '<div class="grafik-bos">Henüz kayıt yok. WaveSnap açık kaldıkça grafik dolacak.</div>'; return; }
  const enYuksek = Math.max(1, ...dilim.map(d => d.indirme + d.yukleme));
  const birim = enYuksek >= 2e9 ? [1e9, "GB"] : [1e6, "MB"];
  const ham = enYuksek / birim[0] / 4;
  const kuvvet = Math.pow(10, Math.floor(Math.log10(ham || 1)));
  const adim = [1, 2, 2.5, 5, 10].map(k => k * kuvvet).find(a => a >= ham) || ham;
  const tavan = adim * 4 * birim[0];
  const n = dilim.length, gen = (G - sol - 4) / n, cub = Math.max(2, Math.min(28, gen * .62));
  const y = v => ust + (1 - v / tavan) * (Y - ust - alt);
  let svg = "";
  for (let i = 0; i <= 4; i++) {
    const v = adim * i, yy = y(v * birim[0]).toFixed(1);
    svg += `<line class="eksen" x1="${sol}" x2="${G}" y1="${yy}" y2="${yy}"/><text class="etiket" x="${sol - 8}" y="${+yy + 4}" text-anchor="end">${sayi(v, v % 1 ? 1 : 0)}</text>`;
  }
  svg += `<text class="etiket" x="0" y="10">${birim[1]}</text>`;
  const etiketAdim = Math.ceil(n / 8);
  dilim.forEach((d, i) => {
    const x = sol + i * gen + (gen - cub) / 2;
    const yi = y(d.indirme), yt = y(d.indirme + d.yukleme);
    svg += `<rect class="cubuk-yukle" x="${x.toFixed(1)}" y="${yt.toFixed(1)}" width="${cub.toFixed(1)}" height="${Math.max(0, yi - yt).toFixed(1)}" rx="2"/>`;
    svg += `<rect class="cubuk-indir" x="${x.toFixed(1)}" y="${yi.toFixed(1)}" width="${cub.toFixed(1)}" height="${Math.max(0, y(0) - yi).toFixed(1)}" rx="2"><title>${bayt(d.indirme)} indirme, ${bayt(d.yukleme)} yükleme</title></rect>`;
    if (i % etiketAdim === 0) {
      const t = new Date(d.zaman * 1000);
      const yazi = tur === "saat" ? t.toLocaleTimeString(YEREL(), { hour: "2-digit", minute: "2-digit" }) : t.toLocaleDateString(YEREL(), { day: "numeric", month: "short" });
      svg += `<text class="etiket" x="${(x + cub / 2).toFixed(1)}" y="${Y - 4}" text-anchor="middle">${yazi}</text>`;
    }
  });
  kutu.innerHTML = `<svg viewBox="0 0 ${G} ${Y}" preserveAspectRatio="none">${svg}</svg>`;
}

// =============================== TAKVİM IZGARASI ===============================
function takvimEditor(dilimler, secili, bos) {
  const veri = (dilimler || Array.from({ length: 7 }, () => [])).map(g => Array.from({ length: 48 }, (_, j) => !!g[j]));
  const kutu = el("div"), izgara = el("div", "takvim"), saatler = el("div", "takvim-saatler");
  saatler.append(el("span"));
  saatler.firstChild.style.gridColumn = "span 1";
  for (let s = 0; s < 24; s += 2) saatler.append(el("span", "", String(s).padStart(2, "0")));
  izgara.append(saatler);
  let boya = null;
  const hucreler = veri.map((gun, d) => {
    const satir = el("div", "takvim-satir");
    satir.append(el("b", "", GUN_KISA[d]));
    const h = gun.map((v, j) => {
      const i = el("i");
      i.classList.toggle("secili", v);
      i.title = `${GUN_KISA[d]} ${String(Math.floor(j / 2)).padStart(2, "0")}:${j % 2 ? "30" : "00"}`;
      i.onmousedown = e => { e.preventDefault(); boya = !veri[d][j]; ayarla(d, j); };
      i.onmouseenter = () => { if (boya !== null) ayarla(d, j); };
      satir.append(i);
      return i;
    });
    izgara.append(satir);
    return h;
  });
  function ayarla(d, j, v = boya) { veri[d][j] = v; hucreler[d][j].classList.toggle("secili", v); }
  document.addEventListener("mouseup", () => boya = null);

  // hızlı doldurma: "her gün 22:00 - 08:00"
  const hizli = el("div", "takvim-hizli"), bas = el("input"), bit = el("input"), gunler = el("div", "gun-secim");
  bas.type = bit.type = "time"; bas.value = "22:00"; bit.value = "08:00";
  const secGun = new Set([0, 1, 2, 3, 4, 5, 6]);
  GUN_KISA.forEach((g, d) => {
    const b = el("button", "secili", g);
    b.onclick = () => { secGun.has(d) ? secGun.delete(d) : secGun.add(d); b.classList.toggle("secili", secGun.has(d)); };
    gunler.append(b);
  });
  const dilim = t => { const [h, m] = t.split(":").map(Number); return h * 2 + (m >= 30 ? 1 : 0); };
  const doldur = v => {
    const a = dilim(bas.value || "00:00"), b = dilim(bit.value || "00:00");
    for (const d of secGun) {
      if (a < b) for (let j = a; j < b; j++) ayarla(d, j, v);
      else { for (let j = a; j < 48; j++) ayarla(d, j, v); for (let j = 0; j < b; j++) ayarla((d + 1) % 7, j, v); }
    }
  };
  hizli.append(bas, "–", bit, gunler, dugme("Ekle", "", () => doldur(true)), dugme("Çıkar", "hafif", () => doldur(false)),
    dugme("Tümünü temizle", "hafif", () => veri.forEach((g, d) => g.forEach((_, j) => ayarla(d, j, false)))));
  const lejant = el("div", "takvim-lejant");
  lejant.append(el("span", "s", secili), el("span", "", bos), el("span", "", "Fareyle tıklayıp sürükleyerek de boyayabilirsiniz"));
  kutu.append(izgara, hizli, lejant);
  kutu.deger = () => veri.map(g => [...g]);
  kutu.etkin = acik => izgara.classList.toggle("kapali", !acik);
  return kutu;
}

// =============================== ZAMANLAMA ===============================
async function modemAyarYukle() {
  const z = $("#zEbeveyn");
  if (!S.modemAyar) [z, $("#zWifi"), $("#zLed"), $("#mAyar")].forEach(k => k.replaceChildren(el("p", "yukleme", "Modemden okunuyor…")));
  try { S.modemAyar = await api("/api/modem-ayar"); } catch (e) { goster(e.message, true); return; }
  zamanlamaCiz(); misafirCiz();
}

function kaydetSatir(metin, is) {
  const s = el("div", "kaydet-satir"), durum = el("span", "durum-yazi");
  const b = dugme(metin, "ana", async () => {
    b.disabled = true; durum.textContent = "Modeme yazılıyor…";
    try { const r = await is(); goster(r.sonuc || "Kaydedildi."); durum.textContent = ""; await modemAyarYukle(); }
    catch (e) { durum.textContent = ""; goster(e.message, true); }
    finally { b.disabled = false; }
  });
  s.append(durum, b);
  return s;
}

function zamanlamaCiz() {
  const m = S.modemAyar;
  // --- internet zamanlaması (WaveSnap'in kendi takvimi; durdurmayı modem yapar) ---
  const z = $("#zEbeveyn");
  z.replaceChildren();
  const takvimler = m.takvimler || {};
  const ekle = dugme("Takvim ekle", "ana", () => takvimDuzenle(""));
  kutuBaslik(z, "İnternet zamanlaması", "Seçtiğiniz cihazların interneti, işaretlediğiniz saatlerde kendiliğinden durur, saat bitince geri gelir. Cihazlar Wi-Fi'de kalır.", ekle);
  z.append(el("p", "bilgi-not", !S.veri.durdur_yuva ? "Takvimi WaveSnap uygular: bilgisayar ve WaveSnap açıkken çalışır. WaveSnap'i kapatırsanız takvimin durdurduğu cihazlar serbest kalır." : `Takvimi WaveSnap uygular: bilgisayar ve WaveSnap açıkken çalışır. Modem aynı anda en fazla ${S.veri.durdur_yuva} cihazın internetini durdurabilir. WaveSnap'i kapatırsanız takvimin durdurduğu cihazlar serbest kalır.`));
  const liste = el("div", "secim-liste");
  liste.style.maxHeight = "none";
  const kayitlar = Object.entries(takvimler);
  if (!kayitlar.length) liste.append(el("div", "bos-yazi", "Henüz takvim yok. \"Takvim ekle\" ile bir cihaz seçip saatleri işaretleyin."));
  for (const [mac, t] of kayitlar) {
    const satir = el("label"), saat = t.reduce((top, g) => top + g.filter(Boolean).length, 0) / 2;
    const c = cihaz(mac);
    satir.append(el("span", "", c ? ad(c) : mac), el("small", "", `haftada ${sayi(saat, saat % 1 ? 1 : 0)} saat kapalı${c && c.durduruldu ? " · şu an durdurulmuş" : ""}`));
    const d = dugme("Düzenle", "", e => { e.preventDefault(); takvimDuzenle(mac); });
    const k = dugme("Kaldır", "hafif", async e => {
      e.preventDefault();
      try { const r = await api("/api/takvim", { mac, takvim: null }); goster(r.sonuc); await modemAyarYukle(); tazele(); }
      catch (x) { goster(x.message, true); }
    });
    satir.append(d, k);
    liste.append(satir);
  }
  z.append(liste);

  function takvimDuzenle(mac) {
    const sec = el("select");
    sec.append(new Option("— cihaz seçin —", ""));
    [...S.veri.cihazlar].filter(c => !c.bu_pc).sort((a, b) => ad(a).localeCompare(ad(b), "tr"))
      .forEach(c => sec.append(new Option(`${ad(c)} · ${c.mac.slice(-5)}`, c.mac)));
    sec.value = mac;
    const editor = takvimEditor(takvimler[mac], "İnternet kapalı", "İnternet açık");
    const etiket = el("label", "alan", "Cihaz");
    etiket.append(sec);
    etiket.style.maxWidth = "420px";
    z.replaceChildren();
    kutuBaslik(z, mac ? "Takvimi düzenle" : "Yeni takvim", "Cihazı seçin, internetin kapalı olacağı saatleri işaretleyin.");
    const satir = el("div", "kaydet-satir");
    const kaydet = dugme("Kaydet", "ana", async () => {
      if (!sec.value) return goster("Önce bir cihaz seçin.", true);
      kaydet.disabled = true;
      try { const r = await api("/api/takvim", { mac: sec.value, takvim: editor.deger() }); goster(r.sonuc); await modemAyarYukle(); tazele(); }
      catch (e) { goster(e.message, true); kaydet.disabled = false; }
    });
    satir.append(dugme("Vazgeç", "hafif", () => zamanlamaCiz()), kaydet);
    z.append(etiket, editor, satir);
  }

  // --- Wi-Fi zamanlaması ---
  const w = $("#zWifi");
  w.replaceChildren();
  const wifi = m.wifi.find(x => x.takvim);
  if (!wifi) kutuBaslik(w, "Wi-Fi zamanlaması", "Bu modem bu özelliği desteklemiyor.");
  else {
    const ac = anahtar(m.wifi.some(x => x.zaman_acik), v => takvim.etkin(v));
    kutuBaslik(w, "Wi-Fi zamanlaması", "İşaretlediğiniz saatlerde Wi-Fi tamamen kapanır, örneğin gece ya da iş yeri kapalıyken. Kablolu cihazlar etkilenmez.", ac);
    w.append(el("p", "bilgi-not", "Henüz denenmedi: bu modemin internet takvimi çalışmadığı için Wi-Fi takviminin de çalıştığından emin değiliz. Herkesi etkilediği için kimse ağı kullanmıyorken bir kez deneyin. Kaydetmek Wi-Fi'yi birkaç saniyeliğine yeniden başlatabilir."));
    const takvim = takvimEditor(wifi.takvim, "Wi-Fi kapalı", "Wi-Fi açık");
    takvim.etkin(ac.deger());
    w.append(takvim, kaydetSatir("Kaydet", () => api("/api/modem-ayar", { tur: "wifi_zaman", acik: ac.deger(), takvim: takvim.deger() })));
  }

  // --- LED ---
  const l = $("#zLed");
  l.replaceChildren();
  if (!m.led) kutuBaslik(l, "Modem ışıkları", "Bu modem bu özelliği desteklemiyor.");
  else {
    const ac = anahtar(m.led.acik);
    kutuBaslik(l, "Modem ışıkları", "Modemin ışıkları her gün bu saatler arasında söner. İnternet ve Wi-Fi etkilenmez.", ac);
    const satir = el("div", "yan-yana"), a = el("label", "alan", "Sönme saati"), b = el("label", "alan", "Yanma saati");
    const ia = el("input"), ib = el("input");
    ia.type = ib.type = "time"; ia.value = m.led.baslangic; ib.value = m.led.bitis;
    a.append(ia); b.append(ib); satir.append(a, b);
    satir.style.maxWidth = "360px";
    l.append(satir, kaydetSatir("Kaydet", () => api("/api/modem-ayar", { tur: "led", acik: ac.deger(), baslangic: ia.value, bitis: ib.value })));
  }
}

// =============================== MİSAFİR AĞI ===============================
function sifreUret() {
  const harf = "abcdefghjkmnpqrstuvwxyz23456789";
  const r = crypto.getRandomValues(new Uint32Array(10));
  return [...r].map(x => harf[x % harf.length]).join("").replace(/(.{5})/, "$1-");
}
function misafirCiz() {
  const k = $("#mAyar"), a = S.modemAyar.ek_ag;
  k.replaceChildren();
  if (!a) { kutuBaslik(k, "Misafir ağı", "Bu modemde ek Wi-Fi ağı bulunamadı."); return; }
  const ac = anahtar(a.acik);
  kutuBaslik(k, "Misafir ağı", "Müşteriler ve misafirler için ayrı adı ve şifresi olan ikinci bir Wi-Fi. Ana ağın şifresini paylaşmanız gerekmez.", ac);
  k.append(el("p", "bilgi-not", "İnternet sağlayıcınız bu modemde misafir ağı bölümünü kapatmış. WaveSnap modemin ek ağ yuvasını kullanır: ad ve şifre ayrıdır, ama misafirlerin sizin cihazlarınızı görmemesi garanti değildir."));
  const ssid = el("input"), sifre = el("input", "mono");
  ssid.value = a.acik ? a.ssid : (a.ssid.startsWith("Misafir") ? t("Misafir Wi-Fi") : a.ssid);
  ssid.maxLength = 32; sifre.value = a.sifre || sifreUret(); sifre.maxLength = 63;
  const l1 = el("label", "alan", "Ağ adı"), l2 = el("label", "alan", "Şifre (en az 8 karakter)");
  l1.append(ssid);
  const sr = el("div", "yan-yana"); sr.style.gridTemplateColumns = "1fr auto"; sr.style.alignItems = "end";
  sr.append(sifre, dugme("Yeni şifre üret", "", () => { sifre.value = sifreUret(); qrCiz("misafir"); }));
  l2.append(sr);
  const ayir = anahtar(a.ayirma);
  const ayirSatir = el("div", "anahtar-satir"), ayirMetin = el("div", "", "Misafirler birbirini görmesin");
  ayirMetin.append(el("small", "", "Misafir ağındaki telefonlar birbirine erişemez."));
  ayirSatir.append(ayirMetin, ayir);
  k.append(l1, l2, ayirSatir, el("p", "kutu-aciklama", "Kaydetmek Wi-Fi'yi yaklaşık 30 saniyeliğine yeniden başlatabilir."),
    kaydetSatir("Kaydet", () => api("/api/modem-ayar", { tur: "ek_ag", acik: ac.deger(), ssid: ssid.value.trim(), sifre: sifre.value, ayirma: ayir.deger() })));
  [ssid, sifre].forEach(i => i.oninput = () => qrCiz("misafir"));
  S.misafirForm = { ssid, sifre };
  qrCiz(S.qrAg || "misafir");
}
function qrMetin(ssid, sifre) {
  const kac = s => s.replace(/([\\;,:"])/g, "\\$1");
  return `WIFI:T:WPA;S:${kac(ssid)};P:${kac(sifre)};;`;
}
async function qrCiz(hangi) {
  S.qrAg = hangi;
  const k = $("#mQr");
  let ssid = "", sifre = "";
  if (hangi === "misafir" && S.misafirForm) { ssid = S.misafirForm.ssid.value.trim(); sifre = S.misafirForm.sifre.value; }
  if (hangi === "ana") {
    try { const r = await api("/api/qr?ag=ana"); ssid = r.ssid; sifre = r.sifre; } catch (e) { return goster(e.message, true); }
  }
  k.replaceChildren();
  const ust = el("div", "kutu-ust"), sekme = el("div", "filtreler");
  sekme.style.margin = "0";
  [["misafir", "Misafir ağı"], ["ana", "Ana ağ"]].forEach(([d, m]) => {
    const b = el("button", d === hangi ? "secili" : "", m); b.onclick = () => qrCiz(d); sekme.append(b);
  });
  ust.append(el("span", "kutu-ad", "QR kodu"), sekme);
  k.append(ust);
  if (!ssid || sifre.length < 8) { k.append(el("p", "qr-bos", "Ağ adı ve en az 8 karakterlik şifre girildiğinde QR kodu burada görünür.")); return; }
  const qr = qrcode(0, "M");
  qr.addData(qrMetin(ssid, sifre)); qr.make();
  const resim = el("div", "qr-resim"), img = el("img");
  img.src = qr.createDataURL(8, 0); img.alt = "Wi-Fi QR kodu";
  resim.append(img);
  const not = hangi === "misafir" && !S.modemAyar.ek_ag.acik ? el("p", "kutu-aciklama", "Misafir ağı henüz açık değil; kaydettikten sonra bu kod çalışır.") : null;
  const yazdir = dugme("Yazdır", "", () => { k.classList.add("qr-yazdir"); window.print(); k.classList.remove("qr-yazdir"); });
  const butonlar = el("div", "qr-dugmeler"); butonlar.append(yazdir);
  k.append(resim, el("div", "qr-ad", ssid), el("div", "qr-sifre", "Şifre: " + sifre), el("p", "kutu-aciklama", "Telefon kamerasıyla okutunca şifre yazmadan bağlanır."), ...(not ? [not] : []), butonlar);
}

// =============================== ARAÇLAR ===============================
function araclarCiz() {
  // --- hız testi ---
  const h = $("#aHiz");
  if (!h.firstChild) {
    kutuBaslik(h, "Hız testi", "Bu bilgisayarın internet hızını ölçer (Cloudflare sunucusuyla, ~20 sn, ~70 MB veri). Kablolu bağlantıda hattın gerçek hızını gösterir.");
    const g = el("div", "hiz-gosterge");
    g.innerHTML = '<div><small>İndirme</small><span><span class="buyuk" id="hIndir">—</span><span class="birim">Mbps</span></span></div>' +
      '<div><small>Yükleme</small><span><span class="orta" id="hYukle">—</span><span class="birim">Mbps</span></span></div>' +
      '<div><small>Gecikme</small><span><span class="orta" id="hGecikme">—</span><span class="birim">ms</span></span></div>';
    const b = dugme("Testi başlat", "ana", hizBaslat); b.id = "hDugme";
    const durum = el("span", "durum-yazi"); durum.id = "hDurum";
    const satir = el("div", "kaydet-satir"); satir.style.justifyContent = "flex-start"; satir.append(b, durum);
    const liste = el("div", "gecmis-liste"); liste.id = "hListe";
    h.append(g, satir, liste);
  }
  // --- hat bilgileri ---
  const t = $("#aHat"), hat = (S.veri && S.veri.hat) || {};
  t.replaceChildren();
  kutuBaslik(t, "İnternet hattı", "Modemin santrale bağlantısı. Senkron hızı, hattın taşıyabileceği en yüksek hızdır.");
  const snr = v => v >= 10 ? ["iyi", "iyi"] : v >= 6 ? ["orta", "orta"] : ["zayif", "zayıf"];
  const satirlar = [
    ["Bağlantı", hat.tur ? `${hat.tur} · ${hat.hat_durumu === "Up" ? "bağlı" : hat.hat_durumu || "—"}`
      : hat.baglanti === "Connected" ? "İnternet bağlı" : hat.baglanti || "—"],
    ["Senkron hızı", hat.indirme_kbps ? `${sayi(hat.indirme_kbps / 1000, 0)} / ${sayi(hat.yukleme_kbps / 1000, 0)} Mbps` : "—"],
    ["Sinyal payı (indirme)", hat.snr_indirme ? `${sayi(hat.snr_indirme, 1)} dB` : "—", hat.snr_indirme && snr(hat.snr_indirme)],
    ["Sinyal payı (yükleme)", hat.snr_yukleme ? `${sayi(hat.snr_yukleme, 1)} dB` : "—", hat.snr_yukleme && snr(hat.snr_yukleme)],
    ["Son kesintiden beri", hat.internet_baslangic ? sure(hat.internet_baslangic) : "—"],
    ["Modem açık", hat.modem_baslangic ? sure(hat.modem_baslangic) : "—"],
    ["Model", [hat.uretici, hat.model].filter(Boolean).join(" ") || "—"], ["Yazılım", hat.yazilim || "—"],
  ].filter(([, v], i) => i === 0 || v !== "—" || yetenek("sayac"));
  const tablo = el("div", "hat-tablo");
  satirlar.forEach(([n, v, o]) => {
    const d = el("div", "bilgi"), b = el("b", "", v);
    if (o) b.append(el("span", "olcek " + o[0], o[1]));
    d.append(el("small", "", n), b); tablo.append(d);
  });
  t.append(tablo);
  if (hat.snr_indirme) t.append(el("p", "kutu-aciklama", "Sinyal payı 6 dB'nin altına inerse hat kopmalara açık olur; o zaman internet sağlayıcınızdan hat kontrolü istenebilir."));

  // --- bağlantı testi ---
  const bt = $("#aTest");
  if (!bt.firstChild) {
    kutuBaslik(bt, "Bağlantı testi", "\"İnternet mi kesik, Wi-Fi mı, modem mi?\" sorusunu adım adım yanıtlar.");
    const sonuc = el("div", "test-sonuc"); sonuc.id = "btSonuc";
    bt.append(dugme("Testi çalıştır", "", baglantiTesti), sonuc);
  }
  // --- yeniden başlat ---
  const yb = $("#aBaslat");
  if (!yb.firstChild) {
    kutuBaslik(yb, "Modemi yeniden başlat", "Modem yavaşladığında ya da takıldığında işe yarar. Yaklaşık 2 dakika internet ve Wi-Fi olmaz.");
    yb.append(dugme("Yeniden başlat…", "tehlike", () => pencereAc([
      el("h3", "", "Modem yeniden başlatılsın mı?"),
      el("p", "", "Bütün cihazların interneti ve Wi-Fi'si yaklaşık 2 dakika kesilir. Sonra her şey kendiliğinden geri gelir."),
      altSatir(vazgec(), dugme("Yeniden başlat", "ana tehlike", async () => {
        pencereKapat();
        try { const r = await api("/api/yeniden-baslat", {}); goster(r.sonuc); } catch (e) { goster(e.message, true); }
      }))])));
  }
  // --- kayıtlar ---
  const k = $("#aKayit");
  if (!k.firstChild) {
    kutuBaslik(k, "Modem kayıtları", "Modemin kendi olay günlüğü: bağlantı kopmaları, DHCP, Wi-Fi olayları.", dugme("Yenile", "", kayitYukle));
    const ara = el("input", "kayit-ara"); ara.placeholder = "Kayıtlarda ara"; ara.oninput = kayitSuz; ara.id = "kayitAra";
    const kutu = el("div", "kayit-kutu"); kutu.id = "kayitKutu";
    k.append(ara, kutu);
  }
}
async function kayitYukle() {
  try { S.kayitlar = (await api("/api/kayitlar")).satirlar; kayitSuz(); } catch (e) { goster(e.message, true); }
}
function kayitSuz() {
  const q = ($("#kayitAra").value || "").toLowerCase(), kutu = $("#kayitKutu");
  kutu.textContent = (S.kayitlar || []).filter(s => !q || s.toLowerCase().includes(q)).join("\n") || "Kayıt yok.";
  kutu.scrollTop = kutu.scrollHeight;
}
async function hizGecmisiYukle() {
  try { const g = await api("/api/gecmis?gun=365"); hizListe(g.hiz_testleri); } catch (e) {}
}
function hizListe(liste) {
  const l = $("#hListe");
  if (!l) return;
  const bas = el("div", "bas");
  ["Tarih", "İndirme", "Yükleme", "Gecikme"].forEach(m => bas.append(el("span", "", m)));
  l.replaceChildren(bas, ...liste.slice(0, 6).map(h => {
    const s = el("div");
    s.append(el("span", "", gun(h.zaman)), el("b", "", sayi(h.indirme, 1) + " Mbps"), el("span", "", sayi(h.yukleme, 1) + " Mbps"), el("span", "", sayi(h.gecikme, 0) + " ms"));
    return s;
  }));
}
async function hizBaslat() {
  const b = $("#hDugme"), durum = $("#hDurum");
  b.disabled = true;
  try { await api("/api/hiz-testi", {}); } catch (e) { b.disabled = false; return goster(e.message, true); }
  ["#hIndir", "#hYukle", "#hGecikme"].forEach(s => yaz($(s), "—"));
  const ad = { gecikme: "Gecikme ölçülüyor…", indirme: "İndirme ölçülüyor…", yukleme: "Yükleme ölçülüyor…" };
  const zaman = setInterval(async () => {
    let d;
    try { d = await api("/api/hiz-testi"); } catch (e) { return; }
    if (d.calisiyor) {
      yaz(durum, ad[d.asama] || "");
      if (d.asama === "indirme") yaz($("#hIndir"), sayi(d.anlik, 0));
      if (d.asama === "yukleme" && d.anlik) yaz($("#hYukle"), sayi(d.anlik, 0));
      return;
    }
    clearInterval(zaman); b.disabled = false; yaz(durum, "");
    if (d.hata) return goster(d.hata, true);
    yaz($("#hIndir"), sayi(d.sonuc.indirme, 1)); yaz($("#hYukle"), sayi(d.sonuc.yukleme, 1)); yaz($("#hGecikme"), sayi(d.sonuc.gecikme, 0));
    hizGecmisiYukle();
  }, 400);
}
async function baglantiTesti() {
  const kutu = $("#btSonuc");
  kutu.replaceChildren(el("div", "test-adim", "Kontrol ediliyor…"));
  let r;
  try { r = await api("/api/baglanti-testi", {}); } catch (e) { return goster(e.message, true); }
  kutu.replaceChildren(...r.adimlar.map(([ok, m]) => { const s = el("div", "test-adim " + (ok ? "iyi" : "kotu")); s.append(el("i"), m); return s; }),
    el("div", "test-ozet", r.ozet));
}

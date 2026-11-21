"use strict";
/* WaveSnap çeviri katmanı.
 *
 * Arayüzün kaynak dili Türkçe. Başka bir dil seçildiğinde, ekrana yazılan her metin (sunucudan gelen mesajlar dahil)
 * web/dil/<kod>.json sözlüğünden çevrilir. Sözlükte "{ad}" içeren anahtarlar kalıptır:
 *   "Son kesintiden beri {sure}": "Since last outage: {sure}"
 * Kalıbın yakaladığı parçalar da ayrıca çevrilir (iç içe). Çevirisi bulunamayan metin olduğu gibi kalır ve
 * CEVIRI.eksik listesine düşer — yeni dil eklerken eksikleri bulmak için tarayıcı konsolunda: [...CEVIRI.eksik]
 *
 * Yeni dil eklemek: web/dil/en.json dosyasını kopyalayıp (örn. de.json) sağ taraftaki değerleri çevirin,
 * "__ad" alanına dilin kendi adını yazın ("Deutsch"). Başka hiçbir yere dokunmanız gerekmez.
 */
const CEVIRI = { dil: "tr", tam: new Map(), kaliplar: [], eksik: new Set(), gozcu: null };
const KAYNAK_HARF = /[çğıöşüÇĞİÖŞÜ]/;

function t(metin) { return cevir(metin); }

function cevir(metin, derinlik = 0) {
  if (CEVIRI.dil === "tr" || !metin) return metin;
  const bas = metin.match(/^\s*/)[0], son = metin.match(/\s*$/)[0], cekirdek = metin.trim();
  if (!cekirdek) return metin;
  const tam = CEVIRI.tam.get(cekirdek);
  if (tam !== undefined) return bas + tam + son;
  if (derinlik < 3) {
    for (const [desen, adlar, hedef] of CEVIRI.kaliplar) {
      const m = cekirdek.match(desen);
      if (!m) continue;
      let sonuc = hedef;
      adlar.forEach((ad, i) => { sonuc = sonuc.split("{" + ad + "}").join(cevir(m[i + 1], derinlik + 1)); });
      return bas + sonuc + son;
    }
  }
  if (KAYNAK_HARF.test(cekirdek) && derinlik === 0) CEVIRI.eksik.add(cekirdek);
  return metin;
}

function cevrilmez(dugum) {
  const e = dugum.nodeType === 1 ? dugum : dugum.parentElement;
  return !e || !!e.closest("script, style, textarea, input, .mono, .kayit-kutu, [data-ham]");
}

function dugumCevir(dugum) {
  if (dugum.nodeType === 3) {
    if (cevrilmez(dugum)) return;
    const eski = dugum.nodeValue, yeni = cevir(eski);
    if (yeni !== eski) dugum.nodeValue = yeni;
    return;
  }
  if (dugum.nodeType !== 1 || cevrilmez(dugum) && !dugum.matches("input, textarea")) return;
  for (const oz of ["placeholder", "title", "aria-label", "alt"]) {
    if (dugum.hasAttribute && dugum.hasAttribute(oz)) {
      const eski = dugum.getAttribute(oz), yeni = cevir(eski);
      if (yeni !== eski) dugum.setAttribute(oz, yeni);
    }
  }
  if (dugum.matches && dugum.matches("input, textarea")) return;
  for (const c of dugum.childNodes) dugumCevir(c);
}

// yüzde işareti Türkçede sayıdan önce (%46), İngilizcede sonra (46%) yazılır
function yuzde(sayi) { const n = Math.round(sayi); return CEVIRI.dil === "tr" ? `%${n}` : `${n}%`; }

function ceviriBaslat(dil, sozluk) {
  CEVIRI.dil = dil;
  document.documentElement.lang = dil;
  if (dil === "tr" || !sozluk) return;
  for (const [k, v] of Object.entries(sozluk)) {
    if (k.startsWith("__")) continue;
    if (k.includes("{")) {
      const adlar = [];
      const desen = "^" + k.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\{(\w+)\}/g, (_, ad) => { adlar.push(ad); return "(.+?)"; }) + "$";
      CEVIRI.kaliplar.push([new RegExp(desen, "s"), adlar, v]);
    } else CEVIRI.tam.set(k, v);
  }
  // uzun kalıplar önce denensin (daha özgül)
  CEVIRI.kaliplar.sort((a, b) => b[0].source.length - a[0].source.length);
  dugumCevir(document.body);
  document.title = cevir(document.title);
  CEVIRI.gozcu = new MutationObserver(degisimler => {
    for (const d of degisimler) {
      if (d.type === "characterData") dugumCevir(d.target);
      else if (d.type === "attributes") dugumCevir(d.target);
      else d.addedNodes.forEach(dugumCevir);
    }
  });
  CEVIRI.gozcu.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true,
    attributeFilter: ["placeholder", "title", "aria-label", "alt"] });
}

const YEREL = () => CEVIRI.dil === "tr" ? "tr-TR" : CEVIRI.dil === "en" ? "en-GB" : CEVIRI.dil;

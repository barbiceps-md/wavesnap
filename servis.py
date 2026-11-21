"""Panelin arka planı: modemi düzenli okur, cihaz listesini hazırlar, işlemleri uygular.

Modem aynı anda tek oturuma izin verdiği için:
  * panel penceresi açıkken oturum açık tutulur ve 4 sn'de bir okunur,
  * pencere kapalıyken dakikada bir "gir - oku - çık" yapılır (yeni cihaz bildirimi için),
    böylece modemin kendi sayfasına girmek isteyen kimse engellenmez,
  * modemde başka bir oturum açıksa panel onu düşürmez, bekler.
"""
import logging
import re
import socket
import threading
import time
from collections import deque

import requests

import bildirim
import depo
import dil
import gecmis
import izleyici
import sifre_kasasi
import surucu
from surucu import GirisHatasi, ModemHatasi, OturumHatasi, Reddedildi, Yetenek

ACIK_ARALIK = 4      # sn — pencere açıkken
KAPALI_ARALIK = 60   # sn — pencere kapalıyken
KALP_SURESI = 20     # sn — bu kadar süre istek gelmezse pencere kapalı sayılır
EK_ARALIK = 30       # sn — engel/sınır/sabit IP listelerini tazeleme sıklığı

log = logging.getLogger("panel")


class ModemMesgul(Exception):
    pass


def rastgele_mac(mac: str) -> bool:
    return bool(int(mac[:2], 16) & 2)


def bos_ad(ad: str) -> bool:
    return not ad or ad.strip().lower() in ("unknown", "unkown host", "unknown host", "*")


_URETICI = None


def uretici(mac: str) -> str:
    """MAC'in ilk yarısından üretici (IEEE listesi). Gizli/rastgele MAC'lerde boş döner."""
    global _URETICI
    if rastgele_mac(mac):
        return ""
    if _URETICI is None:
        import json
        from pathlib import Path
        try:
            _URETICI = json.loads((Path(__file__).resolve().parent / "veri" / "oui.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _URETICI = {}
    return _URETICI.get(mac.replace(":", "")[:6], "")


CINSLER = ("telefon", "bilgisayar", "tablet", "tv", "yazici", "kamera", "oyun", "akilli", "ag", "diger")


def cins_tahmin(host_adi: str, uretici_adi: str, kablo: bool, rastgele: bool) -> str:
    h, u = (host_adi or "").lower(), (uretici_adi or "").lower()
    if re.search(r"ipad|tab", h):
        return "tablet"
    if re.search(r"iphone|android|galaxy|phone|redmi|xiaomi|oppo|vivo|huawei|^v\d{4}|-a\d{2}|pixel|realme|poco", h):
        return "telefon"
    if re.search(r"tv|chromecast|roku|bravia|webos", h) or re.search(r"tcl|vestel", u):
        return "tv"
    if re.search(r"dahua|hikvision|ezviz|imou|reolink|uniview", u + " " + h):
        return "kamera"
    if re.search(r"printer|hp[a-f0-9]{6}|epson|canon|brother", h) or re.search(r"seiko epson|brother ind|canon", u):
        return "yazici"
    if re.search(r"playstation|xbox|nintendo|ps[45]", h) or re.search(r"sony interactive|nintendo", u):
        return "oyun"
    if re.search(r"desktop|laptop|-pc|^pc|macbook|imac|win|book", h) or re.search(r"micro-star|asustek|intel corp|dell|lenovo|hewlett", u):
        return "bilgisayar"
    if re.search(r"tp-link|zyxel|netgear|ubiquiti|mikrotik", u):
        return "ag"
    if re.search(r"espressif|tuya|shelly|sonoff", u + " " + h):
        return "akilli"
    if rastgele and not kablo:
        return "telefon"  # gizli MAC kullananlar neredeyse hep telefon/tablet
    return "bilgisayar" if kablo and h else "diger"


def bu_pc_ip(modem_host: str = "192.168.1.1") -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((modem_host, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return ""


ISARET = depo.KLASOR / "oturum.acik"  # panel modemde oturum açıkken var olur


class Panel:
    def __init__(self):
        self.kilit = threading.RLock()
        self.uyandir = threading.Event()
        self.depo = depo.Depo()
        dil.ayarla(self.depo.ayar.get("dil", "en"))
        self.surucu = surucu.olustur(self.depo.ayar.get("surucu"), self.depo.ayar.get("modem_adres") or "192.168.1.1")
        self.durum = "baslatiliyor"
        self.mesaj = ""
        self.son_kalp = 0.0
        self.son_cikis = 0.0
        self.son_okuma = 0.0
        self.duraklat_bitis = 0.0
        # önceki çalışma oturumu kapatamadan bittiyse (bilgisayar kapandı vb.) modemdeki açık oturum bizimdir
        self.zorla = ISARET.exists()
        self.giris_kapali = False   # şifre reddedildiyse tekrar tekrar denemeyip kilitlenmeyi önler
        self.ek = {"engelli": set(), "sinirlar": {}, "sabitler": {}, "durdurulan": None, "filtre_acik": False}
        self.ek_zaman = 0.0
        self.onceki = {}            # mac -> (zaman, yükleme, indirme)
        self.cihazlar = []
        self.filtre_acik = False
        self.hat = {}               # internet hattı: durum, senkron hızları, açık kalma süreleri
        self.trafik = deque(maxlen=450)  # (zaman, toplam indirme bps, toplam yükleme bps) ~30 dk
        self.gecmis = gecmis.Gecmis()
        self.izleyici = izleyici.KesintiIzleyici(self.gecmis, self.bildir, self.surucu.host)
        self.hiz = izleyici.HizTesti(self.gecmis)
        self.durdurulan = None      # modemde interneti durdurulmuş cihazlar (ebeveyn denetimi listesi)
        self.takvim_zaman = 0.0
        self.aktif_onceki = None    # geldi/gitti olayları için önceki bağlı cihazlar
        self.yok_sayac = {}
        self.calisiyor = True

    # ---------- dışarıdan ----------
    def kalp(self):
        kapaliydi = time.time() - self.son_kalp > KALP_SURESI
        self.son_kalp = time.time()
        if kapaliydi:
            self.uyandir.set()

    def ozet(self) -> dict:
        return {
            "kurulu": self.kurulum_var(),
            "durum": self.durum,
            "mesaj": self.mesaj,
            "son_okuma": self.son_okuma,
            "duraklat_kalan": max(0, int(self.duraklat_bitis - time.time())),
            "bildirim": self.depo.ayar.get("bildirim", True),
            "filtre_acik": self.filtre_acik,
            "hat": self.hat,
            "durdurulan": self.durdurulan or [],
            "durdur_yuva": self.surucu.DURDURMA_YUVASI,
            "surucu": {"kimlik": self.surucu.KIMLIK, "ad": self.surucu.AD, "yetenekler": sorted(self.surucu.yetenekler),
                       "giris": self.surucu.GIRIS_GEREKIR, "tek_oturum": self.surucu.TEK_OTURUM},
            "modem_adres": self.surucu.host,
            "internet": self.izleyici.durum,
            "trafik": list(self.trafik),
            "ayar": {k: self.depo.ayar.get(k) for k in ("tema", "sira", "dil")},
            "cihazlar": self.cihazlar,
        }

    def bildir(self, baslik, metin):
        if self.depo.ayar.get("bildirim", True):
            try:
                bildirim.gonder(dil.t(baslik), dil.t(metin))
            except OSError:
                log.exception("bildirim gönderilemedi")

    def kurulum_var(self) -> bool:
        """Kurulum bitti mi? Sürücü seçilmişse onun gereğine göre; seçim yoksa eski kurulum (şifre kasası) sayılır."""
        if not self.depo.ayar.get("surucu") and not sifre_kasasi.var_mi():
            return False
        if self.surucu.GIRIS_GEREKIR:
            return sifre_kasasi.var_mi() and not self.giris_kapali
        return True

    def surucu_degistir(self, kimlik: str, host: str):
        """Kurulumda seçilen sürücüye ve modem adresine geçer (ayarlara yazılır)."""
        with self.kilit:
            self._oturumu_kapat()
            self.surucu = surucu.olustur(kimlik, host)
            self.depo.ayarla("surucu", self.surucu.KIMLIK)
            self.depo.ayarla("modem_adres", host)
            self.izleyici.modem_host = host
            self.ek = {"engelli": set(), "sinirlar": {}, "sabitler": {}, "durdurulan": None, "filtre_acik": False}
            self.ek_zaman, self.hat, self.cihazlar, self.durdurulan = 0.0, {}, [], None
            self.trafik.clear()
            self.onceki, self.aktif_onceki, self.yok_sayac = {}, None, {}

    def kurulum_tamam(self):
        self.giris_kapali = False
        self.durum, self.mesaj = "baslatiliyor", ""
        self.uyandir.set()

    def duraklat(self, dakika: int):
        with self.kilit:
            self.duraklat_bitis = time.time() + dakika * 60
            self._oturumu_kapat()
            self.durum, self.mesaj = "duraklatildi", ""

    def devam(self, zorla=False):
        self.duraklat_bitis = 0
        self.zorla = zorla
        self.uyandir.set()

    def durdur(self):
        self.calisiyor = False
        self.uyandir.set()
        with self.kilit:
            if self.durdurulan:
                try:
                    self.takvimleri_kaldir()
                except Exception:
                    log.exception("kapanışta takvim temizliği")
            self._oturumu_kapat()
        self.depo.kaydet()

    # ---------- döngü ----------
    def calis(self):
        threading.Thread(target=self.izleyici.calis, daemon=True).start()
        while self.calisiyor:
            acik = time.time() - self.son_kalp < KALP_SURESI
            bekle = ACIK_ARALIK if acik else KAPALI_ARALIK
            if time.time() < self.duraklat_bitis:
                self.durum = "duraklatildi"
                bekle = min(bekle, 5)
            elif not self.kurulum_var():
                self.durum = "kurulum"
                bekle = 3
            else:
                try:
                    with self.kilit:
                        self._oku(tam=time.time() - self.ek_zaman > EK_ARALIK)
                        if time.time() - self.takvim_zaman > 30:
                            self._takvim_uygula()
                        if time.time() - self.son_kalp >= KALP_SURESI:  # okuma sırasında pencere açılmış olabilir
                            self._oturumu_kapat()
                    self.durum, self.mesaj = "canli", ""
                except ModemMesgul:
                    self.durum = "mesgul"
                    self.mesaj = "Modemin kendi sayfasında açık bir oturum var. Panel onu düşürmemek için bekliyor."
                    bekle = min(bekle, 10)
                except GirisHatasi as e:
                    self.giris_kapali = True
                    self.durum, self.mesaj = "kurulum", str(e)
                    log.warning("giriş reddedildi: %s", e)
                except OturumHatasi:
                    self.surucu.unut()
                    bekle = 1
                except requests.RequestException:
                    self.surucu.unut()
                    self.durum, self.mesaj = "ulasilamiyor", f"Modeme ulaşılamıyor ({self.surucu.host})."
                    bekle = min(bekle, 10)
                except Exception as e:  # beklenmeyen: logla, döngüyü öldürme
                    log.exception("okuma hatası")
                    self.surucu.unut()
                    self.durum, self.mesaj = "hata", f"Okuma hatası: {e}"
                    bekle = min(bekle, 10)
            self.uyandir.wait(bekle)
            self.uyandir.clear()

    # ---------- oturum ----------
    def _oturum(self):
        """Sürücünün modemde oturumu açık olsun; açık değilse girer. Oturumu açık sürücüyü döndürür."""
        if not self.surucu.oturum_acik:
            # kendi çıkışımızdan sonra modem birkaç saniye "oturum açık" demeye devam ediyor
            kendi = time.time() - self.son_cikis < 20
            if not self.zorla and not kendi and self.surucu.baskasi_girisli():
                raise ModemMesgul()
            self.zorla = False
            if self.surucu.GIRIS_GEREKIR:
                kimlik = sifre_kasasi.oku()
                if not kimlik:  # ilk kurulumda arayüz şifre girilmeden modem ayarını sorabilir
                    raise Reddedildi("Önce modem bağlantısını kurun.")
                self.surucu.giris(*kimlik)
                ISARET.parent.mkdir(parents=True, exist_ok=True)
                ISARET.touch()
            else:
                self.surucu.giris("", "")
            log.info("modeme giriş yapıldı")
        return self.surucu

    def _oturumu_kapat(self):
        if self.surucu.oturum_acik:
            self.surucu.cikis()
            self.son_cikis = time.time()
            ISARET.unlink(missing_ok=True)

    # ---------- okuma ----------
    def _ek_oku(self):
        s = self._oturum()
        self.ek = s.oku_ek()
        self.filtre_acik = self.ek["filtre_acik"]
        self.durdurulan = self.ek["durdurulan"]
        self.ek_zaman = time.time()
        if Yetenek.HAT in s.yetenekler:
            try:
                self._hat_oku()
            except ModemHatasi:  # başka modellerde bu nesneler olmayabilir; panelin geri kalanı çalışsın
                log.info("hat bilgisi okunamadı", exc_info=True)

    def _hat_oku(self):
        h = self.surucu.oku_hat()
        simdi = time.time()
        yeni_bas = simdi - h["internet_sure"] if h.get("internet_sure") else None
        eski_bas = self.hat.get("internet_baslangic")
        if yeni_bas and eski_bas and yeni_bas - eski_bas > 120:
            self.gecmis.olay("", "yeniden_baglandi", "Modemin internet bağlantısı yeniden kuruldu")
        self.hat = {
            "baglanti": h.get("baglanti", ""),
            "internet_baslangic": yeni_bas,
            "modem_baslangic": simdi - h["modem_sure"] if h.get("modem_sure") else None,
            "tur": h.get("tur", ""),
            "hat_durumu": h.get("hat_durumu", ""),
            "indirme_kbps": h.get("indirme_kbps", 0),
            "yukleme_kbps": h.get("yukleme_kbps", 0),
            "snr_indirme": h.get("snr_indirme", 0),
            "snr_yukleme": h.get("snr_yukleme", 0),
            "model": h.get("model", ""),
            "yazilim": h.get("yazilim", ""),
        }

    def _oku(self, tam=False):
        if tam or not self.ek_zaman:
            self._ek_oku()
        self._derle(self._oturum().oku_cihazlar())
        self.son_okuma = time.time()

    def _derle(self, satirlar):
        simdi = time.time()
        pc_ip = bu_pc_ip(self.surucu.host)

        gorulen, liste, yeniler = set(), [], []
        for r in satirlar:
            mac = r["mac"].upper()
            if not mac or mac in gorulen:
                continue
            gorulen.add(mac)
            ind, yuk, aktif, kablo, bant = r["indirilen"], r["yuklenen"], r["aktif"], r["kablo"], r["bant"]
            # anlık hız: iki okuma arasındaki bayt farkı
            hiz_ind = hiz_yuk = 0
            once = self.onceki.get(mac)
            if once and aktif and once[2]:  # geçmiş: iki okuma arasındaki bayt farkı (sayaç sıfırlandıysa yeni değerin tamamı)
                fi, fy = ind - once[2], yuk - once[1]
                self.gecmis.kullanim(mac, fi if fi >= 0 else ind, fy if fy >= 0 else yuk, simdi)
            if aktif and once and simdi - once[0] > 0.5:
                dt = simdi - once[0]
                hiz_yuk = max(0, yuk - once[1]) * 8 / dt
                hiz_ind = max(0, ind - once[2]) * 8 / dt
            self.onceki[mac] = (simdi, yuk, ind)

            host_adi = "" if bos_ad(r.get("host_adi", "")) else r["host_adi"]
            ip = r.get("ip", "")
            if self.depo.gor(mac, host_adi, ip, ("kablo" if kablo else bant) if aktif else None, aktif) and aktif:
                self.gecmis.olay(mac, "yeni", ip)
                yeniler.append((mac, host_adi, ip, "Kablo" if kablo else f"{bant} GHz".replace(".", ",") if bant else "Ağ"))
            liste.append(self._cihaz(mac, host_adi, ip, aktif, kablo, bant, ind, yuk, hiz_ind, hiz_yuk,
                                     r.get("baglanti", 0), pc_ip))

        # modemin listesinde olmayan ama daha önce gördüklerimiz ve engellediklerimiz
        for mac in list(self.depo.cihazlar) + list(self.ek["engelli"]):
            if mac not in gorulen:
                gorulen.add(mac)
                c = self.depo.cihazlar.get(mac, {})
                # tam sürücüler Wi-Fi/kablo ayrımını bilir (eski davranış: bilinmiyorsa Wi-Fi); temel modda bilinmez
                kablo = True if c.get("bant") == "kablo" else False if c.get("bant") in ("2.4", "5", "6") or self.surucu.GIRIS_GEREKIR else None
                liste.append(self._cihaz(mac, c.get("host_adi", ""), c.get("ip", ""), False, kablo,
                                         None, 0, 0, 0, 0, 0, pc_ip))
        self.cihazlar = liste
        toplam = (sum(c["hiz_indirme"] for c in liste), sum(c["hiz_yukleme"] for c in liste))
        self.trafik.append((round(simdi, 1), *toplam))
        self.gecmis.trafik(simdi, *toplam)
        self._varlik({c["mac"] for c in liste if c["aktif"]}, {c["mac"]: c["ip"] for c in liste})
        self.depo.kaydet()

        for mac, ad, ip, bant in yeniler:
            self.bildir("Yeni cihaz bağlandı", f"{ad or dil.t('Adı bilinmeyen cihaz')} · {ip} · {dil.t(bant)}")

    def _cihaz_yenile(self, eski):
        """Yalnız depodaki (elle girilen) alanları tazeler; modemden gelen anlık değerler korunur."""
        c = self.depo.cihazlar.get(eski["mac"], {})
        yeni = dict(eski, ad=c.get("ad", ""), grup=c.get("grup", ""), not_=None)
        yeni.pop("not_")
        yeni["not"] = c.get("not", "")
        yeni["guvenilir"] = bool(c.get("guvenilir"))
        yeni["cins_elle"] = bool(c.get("cins"))
        yeni["cins"] = c.get("cins") or cins_tahmin(eski["host_adi"], eski["uretici"], eski["tur"] == "kablo", eski["rastgele"])
        return yeni

    def _varlik(self, aktifler, ipler):
        """Geldi/gitti olayları. Wi-Fi listeleri anlık titreyebildiği için 'gitti' 3 okuma üst üste yoksa yazılır."""
        if self.aktif_onceki is None:
            self.aktif_onceki = set(aktifler)
            return
        for mac in aktifler - self.aktif_onceki:
            if not self.yok_sayac.pop(mac, None):
                self.gecmis.olay(mac, "geldi", ipler.get(mac, ""))
        for mac in self.aktif_onceki - aktifler:
            self.yok_sayac[mac] = 1
        for mac in list(self.yok_sayac):
            if mac in aktifler:
                self.yok_sayac.pop(mac)
            elif mac not in self.aktif_onceki or self.yok_sayac[mac] > 1:
                self.yok_sayac[mac] += 1
                if self.yok_sayac[mac] == 3:
                    self.gecmis.olay(mac, "gitti", ipler.get(mac, ""))
                    self.yok_sayac.pop(mac)
        self.aktif_onceki = set(aktifler) | set(self.yok_sayac)

    def _cihaz(self, mac, host_adi, ip, aktif, kablo, bant, ind, yuk, hiz_ind, hiz_yuk, baglanti, pc_ip):
        c = self.depo.cihazlar.get(mac, {})
        uret = uretici(mac)
        return {
            "mac": mac,
            "uretici": uret,
            "cins": c.get("cins") or cins_tahmin(host_adi or c.get("host_adi", ""), uret, kablo, rastgele_mac(mac)),
            "cins_elle": bool(c.get("cins")),
            "grup": c.get("grup", ""),
            "not": c.get("not", ""),
            "guvenilir": bool(c.get("guvenilir")),
            "durduruldu": mac in (self.durdurulan or []),
            "takvimli": mac in (self.depo.ayar.get("takvimler") or {}),
            "ad": c.get("ad", ""),
            "host_adi": host_adi or c.get("host_adi", ""),
            "ip": ip or c.get("ip", ""),
            "aktif": aktif,
            "tur": "kablo" if kablo else "wifi" if kablo is False else "bilinmiyor",
            "bant": bant,
            "indirilen": ind,
            "yuklenen": yuk,
            "hiz_indirme": round(hiz_ind),
            "hiz_yukleme": round(hiz_yuk),
            "baglanti": baglanti,
            "ilk": c.get("ilk"),
            "son": c.get("son"),
            "yeni": not c.get("tohum") and bool(c.get("ilk")) and time.time() - c["ilk"] < 86400,
            "rastgele": rastgele_mac(mac),
            "engelli": mac in self.ek["engelli"],
            "sinir": self.ek["sinirlar"].get(mac),
            "sabit_ip": self.ek["sabitler"].get(mac),
            "bu_pc": aktif and ip == pc_ip,
        }

    # ---------- işlemler ----------
    def islem(self, ad: str, mac: str, veri: dict) -> str:
        mac = mac.upper()
        if not re.fullmatch(r"[0-9A-F]{2}(:[0-9A-F]{2}){5}", mac):
            raise Reddedildi("Geçersiz MAC adresi.")
        if ad == "adlandir":
            self.depo.adlandir(mac, (veri.get("ad") or "").strip())
            self.cihazlar = [self._cihaz_yenile(c) if c["mac"] == mac else c for c in self.cihazlar]
            return "Ad kaydedildi."
        if ad == "meta":
            alanlar = {}
            if "cins" in veri:
                alanlar["cins"] = veri["cins"] if veri["cins"] in CINSLER else ""
            if "grup" in veri:
                alanlar["grup"] = str(veri["grup"] or "").strip()[:30]
            if "not" in veri:
                alanlar["not"] = str(veri["not"] or "").strip()[:300]
            if "guvenilir" in veri:
                alanlar["guvenilir"] = bool(veri["guvenilir"])
            self.depo.meta(mac, alanlar)
            self.cihazlar = [self._cihaz_yenile(c) if c["mac"] == mac else c for c in self.cihazlar]
            return "Kaydedildi."
        if time.time() < self.duraklat_bitis:
            raise Reddedildi("Panel duraklatıldı; önce Ayarlar'dan devam ettirin.")
        islevler = {
            "durdur": self._durdur, "devam": self._devam,
            "engelle": self._engelle, "engel_kaldir": self._engel_kaldir,
            "sinir": self._sinir, "sinir_kaldir": self._sinir_kaldir,
            "sabit": self._sabit, "sabit_kaldir": self._sabit_kaldir,
        }
        if ad not in islevler:
            raise Reddedildi("Bilinmeyen işlem.")
        gerekli = {"durdur": Yetenek.DURDUR, "devam": Yetenek.DURDUR, "engelle": Yetenek.ENGELLE,
                   "engel_kaldir": Yetenek.ENGELLE, "sinir": Yetenek.SINIR, "sinir_kaldir": Yetenek.SINIR,
                   "sabit": Yetenek.SABIT_IP, "sabit_kaldir": Yetenek.SABIT_IP}[ad]
        if gerekli not in self.surucu.yetenekler:
            raise Reddedildi("Bu modem bu özelliği desteklemiyor.")
        with self.kilit:
            try:
                self._ek_oku()  # karar vermeden önce modemin şu anki hali
                t = time.time()
                sonuc = islevler[ad](mac, veri)
                log.info("%s %s -> %s (%.1f sn)", ad, mac, sonuc, time.time() - t)
                self._oku(tam=True)
                return sonuc
            except ModemMesgul:
                raise Reddedildi("Modemin kendi sayfasında açık bir oturum var; o kapanınca tekrar deneyin.")

    # ---------- interneti durdurma (modemin ebeveyn denetimi: en fazla 4 cihaz) ----------
    # 20 Kas denemesi: modemin kendi takvimi bu yazılımda çalışmıyor; ama "izinli siteler" kipinde boş listeyle açılan
    # kısıt, listedeki cihazların internetini anında ve kesin keser. Takvimi WaveSnap kendisi uygular.
    def _durdurma_yaz(self, liste):
        pc = next((c["mac"] for c in self.cihazlar if c.get("bu_pc")), "")
        self._oturum().durdurulanlari_yaz(list(liste), pc)
        self.durdurulan = list(liste)

    def _istenen_durdurma(self):
        elle = list(self.depo.ayar.get("durdur_elle", []))
        simdi = time.localtime()
        dilim = simdi.tm_hour * 2 + (1 if simdi.tm_min >= 30 else 0)
        takvimden = [mac for mac, t in (self.depo.ayar.get("takvimler") or {}).items()
                     if t and t[simdi.tm_wday][dilim] and mac not in elle]
        hepsi = elle + takvimden
        return hepsi[:self.surucu.DURDURMA_YUVASI], len(hepsi) > self.surucu.DURDURMA_YUVASI

    def _takvim_uygula(self, zorla=False):
        self.takvim_zaman = time.time()
        if self.durdurulan is None:
            return
        istenen, tasti = self._istenen_durdurma()
        if zorla or sorted(istenen) != sorted(self.durdurulan):
            onceki = set(self.durdurulan)
            self._durdurma_yaz(istenen)
            for mac in set(istenen) - onceki:
                self.gecmis.olay(mac, "durduruldu", "")
            for mac in onceki - set(istenen):
                self.gecmis.olay(mac, "devam", "")
            log.info("durdurulan cihazlar: %s", istenen)
        if tasti:
            log.warning("aynı anda 4'ten fazla cihaz durdurulmak istendi; fazlası atlandı")

    def _durdur(self, mac, veri):
        if any(c["mac"] == mac and c.get("bu_pc") for c in self.cihazlar):
            raise Reddedildi("Bu bilgisayarın interneti durdurulamaz; WaveSnap'i kullandığınız bilgisayar bu.")
        if self.durdurulan is None:
            raise Reddedildi("Bu modemde interneti durdurma özelliği okunamadı.")
        elle = [m for m in self.depo.ayar.get("durdur_elle", []) if m != mac]
        if mac not in self.durdurulan and len(set(elle) | set(self.durdurulan)) >= self.surucu.DURDURMA_YUVASI:
            raise Reddedildi(f"Modem aynı anda en fazla {self.surucu.DURDURMA_YUVASI} cihazın internetini durdurabiliyor.")
        self.depo.ayarla("durdur_elle", elle + [mac])
        self._takvim_uygula(zorla=True)
        return "İnternet durduruldu. Cihaz Wi-Fi'de kalır ama internete çıkamaz."

    def _devam(self, mac, veri):
        self.depo.ayarla("durdur_elle", [m for m in self.depo.ayar.get("durdur_elle", []) if m != mac])
        istenen, _ = self._istenen_durdurma()
        self._takvim_uygula(zorla=True)
        if mac in istenen:
            return "Elle durdurma kaldırıldı, ama bu cihazın takvimi şu an 'internet kapalı' diyor."
        return "İnternet yeniden açıldı."

    def takvim_kaydet(self, mac, takvim):
        takvimler = dict(self.depo.ayar.get("takvimler") or {})
        if takvim and any(any(g) for g in takvim):
            takvimler[mac] = [[bool(x) for x in (list(g) + [False] * 48)[:48]] for g in list(takvim)[:7]]
        else:
            takvimler.pop(mac, None)
        self.depo.ayarla("takvimler", takvimler)
        self._takvim_uygula(zorla=True)
        return "Takvim kaydedildi." if mac in takvimler else "Takvim kaldırıldı."

    def takvimleri_kaldir(self):
        """Düzgün kapanışta yalnız takvimin durdurduğu cihazları serbest bırak: WaveSnap kapalıyken takvim
        işlemez, cihaz saatin bitişini beklerken sonsuza dek kesik kalmasın. Elle durdurulanlar kalır."""
        elle = list(self.depo.ayar.get("durdur_elle", []))[:self.surucu.DURDURMA_YUVASI]
        if sorted(self.durdurulan or []) != sorted(elle):
            self._oturum()
            self._durdurma_yaz(elle)

    def _engelle(self, mac, veri):
        return self.surucu.engelle(mac)

    def _engel_kaldir(self, mac, veri):
        return self.surucu.engel_kaldir(mac)

    def _sinir(self, mac, veri):
        try:
            mbps = float(veri.get("mbps"))
        except (TypeError, ValueError):
            raise Reddedildi("Hız değeri okunamadı.")
        if not 0.5 <= mbps <= 500:
            raise Reddedildi("Hız 0,5 ile 500 Mbps arasında olmalı.")
        return self.surucu.sinir(mac, mbps)

    def _sinir_kaldir(self, mac, veri):
        return self.surucu.sinir_kaldir(mac)

    def _sabit(self, mac, veri):
        ip = (veri.get("ip") or "").strip()
        onek = self.surucu.lan_onek()
        son = ip[len(onek):] if ip.startswith(onek) else ""
        if not (son.isdigit() and len(son) <= 3 and 2 <= int(son) <= 254):
            raise Reddedildi(f"IP {onek}2 – {onek}254 aralığında olmalı.")
        for m, a in self.ek["sabitler"].items():
            if a == ip and m != mac:
                raise Reddedildi(f"{ip} başka bir cihaza ayrılmış.")
        if self.ek["sabitler"].get(mac) == ip:
            return "Bu adres zaten sabit."
        return self.surucu.sabit(mac, ip)

    def _sabit_kaldir(self, mac, veri):
        return self.surucu.sabit_kaldir(mac)

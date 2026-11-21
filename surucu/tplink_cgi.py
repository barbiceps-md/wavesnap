"""TP-Link — VC220-G3u türü web arayüzü (`/cgi?` isteği, RSA'lı giriş). Türk Telekom yazılımında denendi.

Modemin kendi web arayüzünün kullandığı yollar:
  /cgi/getParm  -> RSA açık anahtarı (nn, ee)
  /cgi/login    -> RSA ile şifrelenmiş kullanıcı adı + base64(şifre)
  /cgi?<n>      -> veri okuma/yazma ("[NESNE#yol#yol]sıra,adet" biçimi)

Bilinen huylar (20 Kas 2026 denemeleri):
  * aynı anda tek oturum; 5 hatalı girişte 10 dk kilit; Referer başlığı şart, oturumsuz istek HTTP 500
  * ebeveyn denetimi takvimi çalışmıyor; "izinli siteler" kipi + boş liste anında ve kesin keser (en fazla 4 cihaz)
  * trafik sayaçları IP'ye bağlı: aynı IP'yi önceden almış çevrim dışı kayıt, şimdiki sahibinin sayacını gösterir
  * MAC filtresini açmak Wi-Fi'yi ~26 sn yeniden başlatır; "allow" kuralında listede olmayan herkes kopar
  * Wi-Fi yazımları 20-26 sn sürer; anahtar adlarının büyük/küçük harfi tutarsız
"""
import base64
import logging
import re
import threading
import time

import requests
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .temel import GirisHatasi, ModemHatasi, OturumHatasi, Reddedildi, Surucu, Yetenek

log = logging.getLogger("panel")

GUNLER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # panelin sırası: Pazartesi..Pazar
EBEVEYN_YUVA = 4
GRUP_SAYISI = 18
LAN_YOLU = "1,1,0,0,0,0"


# ---------------------------------------------------------------------------------------------
# Takvim biçimi: her gün iki yarım güne (Am/Pm) bölünür, her yarım gün 24 bitlik bir sayıdır;
# bit j = o yarım günün j. yarım saati (Am bit 0 = 00:00-00:30, Pm bit 0 = 12:00-12:30).
# Panel takvimi 7 × 48 dilimlik liste olarak taşır; gün 0 = Pazartesi.
# ---------------------------------------------------------------------------------------------
def takvim_coz(kayit: dict) -> list:
    """Modem kaydı -> 7 gün × 48 dilim (True = seçili)."""
    sonuc = []
    for g in GUNLER:
        am, pm = int(kayit.get(g + "am", 0) or 0), int(kayit.get(g + "pm", 0) or 0)
        sonuc.append([bool(am >> j & 1) for j in range(24)] + [bool(pm >> j & 1) for j in range(24)])
    return sonuc


def takvim_yaz(dilimler: list) -> dict:
    """7 × 48 dilim -> modemin alanları (monAm=..., ...)."""
    alan = {}
    for g, gun in zip(GUNLER, dilimler):
        gun = [bool(x) for x in (list(gun) + [False] * 48)[:48]]
        alan[g + "Am"] = sum(1 << j for j in range(24) if gun[j])
        alan[g + "Pm"] = sum(1 << j for j in range(24) if gun[24 + j])
    return alan


# ---------------------------------------------------------------------------------------------
# Düşük seviye istemci: modemle HTTP üzerinden konuşur
# ---------------------------------------------------------------------------------------------
class Istemci:
    # Eylem türleri (modemin lib.js'iyle aynı)
    GET, SET, ADD, DEL, GL, GS, OP = 1, 2, 3, 4, 5, 6, 7
    BOS = "0,0,0,0,0,0"

    def __init__(self, adres: str = "http://192.168.1.1"):
        self.adres = adres
        self.oturum = requests.Session()
        self.oturum.headers.update({
            "Referer": adres + "/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        })
        self.token = None
        self.kilit = threading.Lock()

    def _rsa(self, metin: str, nn: str, ee: str) -> str:
        anahtar = rsa.RSAPublicNumbers(int(ee, 16), int(nn, 16)).public_key()
        sifreli = anahtar.encrypt(metin.encode("utf-8"), padding.PKCS1v15())
        return sifreli.hex().rjust(256, "0")

    def _post(self, yol: str, veri=None, zaman=8):
        basliklar = {}
        if self.token:
            basliklar["TokenID"] = self.token
        return self.oturum.post(self.adres + yol, data=veri, headers=basliklar, timeout=zaman)

    def mesgul_mu(self) -> dict:
        m = self._post("/cgi/getBusy").text
        return {"girisli": "isLogined=1" in m, "mesgul": "isBusy=1" in m}

    def giris(self, kullanici: str, sifre: str) -> None:
        with self.kilit:
            parm = self._post("/cgi/getParm").text
            nn = re.search(r'nn="([0-9A-Fa-f]+)"', parm).group(1)
            ee = re.search(r'ee="([0-9A-Fa-f]+)"', parm).group(1)
            ad = self._rsa(kullanici, nn, ee)
            sf = self._rsa(base64.b64encode(sifre.encode("utf-8")).decode(), nn, ee)
            self.token = None
            self._post(f"/cgi/login?UserName={ad}&Passwd={sf}&Action=1&LoginStatus=0")
            ana = self.oturum.get(self.adres + "/", timeout=8).text
            if "pcPassword" in ana:
                hata = re.search(r"authTimes=(\d+)", ana)
                deneme = int(hata.group(1)) if hata else 0
                raise GirisHatasi(f"Modem girişi kabul etmedi (hatalı deneme sayısı: {deneme}/5)")
            t = re.search(r'token\s*=\s*"([^"]+)"', ana)
            self.token = t.group(1) if t else None

    def cikis(self) -> None:
        try:
            self._post("/cgi/logout")
        except requests.RequestException:
            pass
        self.token = None

    def istek(self, eylemler):
        """eylemler: [(tür, nesne, yol, üst_yol, öznitelikler)] -> her eylem için sonuç.

        GET/SET -> dict, GL/GS -> list[dict], diğerleri -> None.
        Modem hata kodu döndürürse ModemHatasi fırlatır.
        """
        govde = ""
        url = []
        for i, (tur, nesne, yol, ust, oz) in enumerate(eylemler):
            yol = yol or self.BOS
            ust = ust or self.BOS
            if isinstance(oz, dict):
                oz = [f"{k}={v}" for k, v in oz.items()]
            oz = list(oz or [])
            metin = "".join(a + "\r\n" for a in oz)
            url.append(str(tur))
            govde += f"[{nesne}#{yol}#{ust}]{i},{len(oz)}\r\n{metin}"
        # Wi-Fi ayarı yazınca modem radyoyu yeniden başlatır, cevap 10-20 sn sürebilir
        yazma = any(e[0] in (self.SET, self.ADD, self.DEL) for e in eylemler)
        with self.kilit:
            r = self._post("/cgi?" + "&".join(url), govde.encode("utf-8"), zaman=40 if yazma else 10)
        if r.status_code == 500 or "[error]" not in r.text:
            # oturum düşmüşse modem 500 döndürüyor
            raise OturumHatasi(f"oturum düştü (HTTP {r.status_code})")
        if r.status_code != 200:
            raise ModemHatasi(f"HTTP {r.status_code}")
        return self._coz(r.text, eylemler)

    def _coz(self, metin, eylemler):
        sonuc = []
        for tur, *_ in eylemler:
            sonuc.append([] if tur in (self.GL, self.GS) else ({} if tur in (self.GET, self.SET) else None))
        ornek = None
        for satir in metin.split("\n"):
            satir = satir.rstrip("\r")
            if not satir:
                continue
            if satir.startswith("["):
                kapa = satir.index("]")
                yol = satir[1:kapa]
                no = int(satir[kapa + 1:] or 0)
                if yol == "error":
                    if no:
                        raise ModemHatasi(f"modem hata kodu {no}")
                    ornek = None
                    continue
                hedef = sonuc[no] if no < len(sonuc) else None
                if isinstance(hedef, list):
                    ornek = {"__yol": yol}
                    hedef.append(ornek)
                elif isinstance(hedef, dict):
                    ornek = hedef
                    ornek["__yol"] = yol
                else:
                    ornek = None
            elif ornek is not None and "=" in satir:
                k, v = satir.split("=", 1)
                ornek[k.lower()] = v  # modem büyük/küçük harfi tutarsız döndürüyor
        return sonuc


M = Istemci


# ---------------------------------------------------------------------------------------------
# Sürücü
# ---------------------------------------------------------------------------------------------
class TplinkCgi(Surucu):
    KIMLIK = "tplink_cgi"
    AD = "TP-Link (VC220-G3u türü arayüz)"
    yetenekler = frozenset({
        Yetenek.CIHAZLAR, Yetenek.SAYAC, Yetenek.ENGELLE, Yetenek.DURDUR, Yetenek.SINIR, Yetenek.SABIT_IP,
        Yetenek.HAT, Yetenek.WIFI_ZAMAN, Yetenek.LED, Yetenek.MISAFIR, Yetenek.WIFI_QR, Yetenek.YENIDEN_BASLAT,
        Yetenek.KAYITLAR,
    })
    DURDURMA_YUVASI = EBEVEYN_YUVA
    SINIR_YUVASI = GRUP_SAYISI

    def __init__(self, host: str = "192.168.1.1"):
        super().__init__(host)
        self.adres = f"http://{host}"
        self.ist = None
        self._kimlik = None          # yeniden giriş için (yalnız bellekte)
        self.wlan = []
        self.ham = {"engel": {}, "sinif": [], "grup": [], "shape": {}, "sabit": []}

    @classmethod
    def tani(cls, host):
        """Giriş sayfasının kullandığı RSA anahtar isteği: bu arayüzde nn= ve ee= döner (şifre gönderilmez)."""
        try:
            r = requests.post(f"http://{host}/cgi/getParm", headers={"Referer": f"http://{host}/"}, timeout=3)
            return 'nn="' in r.text and 'ee="' in r.text
        except requests.RequestException:
            return False

    # ---------- oturum ----------
    @property
    def oturum_acik(self) -> bool:
        return self.ist is not None

    def baskasi_girisli(self) -> bool:
        return Istemci(self.adres).mesgul_mu()["girisli"]

    def giris(self, kullanici, sifre):
        ist = Istemci(self.adres)
        ist.giris(kullanici, sifre)
        self.ist, self._kimlik = ist, (kullanici, sifre)

    def cikis(self):
        if self.ist is not None:
            self.ist.cikis()
            self.ist = None

    def unut(self):
        self.ist = None

    def _istek(self, eylemler):
        """Oturum düştüyse bir kez yeniden girip tekrar dener."""
        t = time.time()
        try:
            if self.ist is None:
                raise OturumHatasi("oturum yok")
            try:
                return self.ist.istek(eylemler)
            except OturumHatasi:
                if not self._kimlik:
                    raise
                log.info("oturum düşmüştü, yeniden giriliyor")
                self.ist = None
                self.giris(*self._kimlik)
                return self.ist.istek(eylemler)
        finally:
            if time.time() - t > 3:
                log.info("yavaş istek %.1f sn: %s", time.time() - t, [e[1] for e in eylemler])

    # ---------- okuma ----------
    @staticmethod
    def _bant(w) -> str:
        return "5" if "5" in w.get("x_tp_band", "") else "2.4"

    def oku_ek(self) -> dict:
        wl, = self._istek([(M.GL, "LAN_WLAN", None, None,
                            ["name", "X_TP_Band", "Status", "MACAddressControlEnabled", "X_TP_MACAddressControlRule"])])
        self.wlan = [w for w in wl if w.get("status") == "Up"]
        tablolar = self._istek([(M.GS, "LAN_WLAN_MACTABLEENTRY", None, w["__yol"], ["Enabled", "MACAddress", "Description"])
                                for w in self.wlan]) if self.wlan else []
        engel = {}
        for w, tablo in zip(self.wlan, tablolar):
            for e in tablo:
                engel.setdefault(e["macaddress"].upper(), []).append(e["__yol"])
        sh, gr, cl, st = self._istek([(M.GET, "SHAPE", None, None, None), (M.GL, "SHAPE_GROUP", None, None, None),
                                      (M.GL, "SHAPE_CLASS", None, None, None), (M.GL, "LAN_DHCP_STATIC_ADDR", None, None, None)])
        self.ham = {"engel": engel, "shape": sh, "grup": gr, "sinif": cl, "sabit": st}

        sinirlar = {}
        gruplar = {g.get("id"): g for g in gr}
        for c in cl:
            g = gruplar.get(c.get("classgroupid"))
            if c.get("macaddress") and g:
                sinirlar[c["macaddress"].upper()] = round(int(g.get("downmaxbw", 0)) / 1024, 1)
        try:
            fw, hostlar = self._istek([(M.GET, "FIREWALL", None, None, ["enalbeParentCtrl"]),
                                       (M.GL, "INTERNAL_HOST", None, None, ["entryName", "mac"])])
            liste = [h["mac"].upper() for h in hostlar if h.get("entryname", "").startswith("childMac") and h.get("mac")]
            durdurulan = liste if fw.get("enalbeparentctrl") == "1" else []
        except ModemHatasi:
            durdurulan = None
        return {
            "engelli": set(engel),
            "sinirlar": sinirlar,
            "sabitler": {s.get("chaddr", "").upper(): s.get("yiaddr") for s in st},
            "durdurulan": durdurulan,
            "filtre_acik": any(w.get("macaddresscontrolenabled") == "1" for w in self.wlan),
        }

    def oku_hat(self) -> dict:
        ppp, dsl, cihaz = self._istek([
            (M.GL, "WAN_PPP_CONN", None, None, ["enable", "connectionStatus", "uptime", "lastConnectionError"]),
            (M.GL, "WAN_DSL_INTF_CFG", None, None, ["status", "modulationType", "upstreamCurrRate", "downstreamCurrRate",
                                                     "upstreamNoiseMargin", "downstreamNoiseMargin"]),
            (M.GET, "IGD_DEV_INFO", None, None, ["modelName", "softwareVersion", "upTime"]),
        ])
        baglanti = next((p for p in ppp if p.get("enable") == "1"), {})
        hat = next((d for d in dsl if d.get("status") == "Up"), dsl[0] if dsl else {})
        sayi = lambda v: int(v) if str(v).lstrip("-").isdigit() else 0
        return {
            "baglanti": baglanti.get("connectionstatus", ""),
            "internet_sure": sayi(baglanti.get("uptime")) if baglanti.get("uptime") else None,
            "modem_sure": sayi(cihaz.get("uptime")) if cihaz.get("uptime") else None,
            "tur": hat.get("modulationtype", ""),
            "hat_durumu": hat.get("status", ""),
            "indirme_kbps": sayi(hat.get("downstreamcurrrate")),
            "yukleme_kbps": sayi(hat.get("upstreamcurrrate")),
            "snr_indirme": sayi(hat.get("downstreamnoisemargin")) / 10,
            "snr_yukleme": sayi(hat.get("upstreamnoisemargin")) / 10,
            "model": cihaz.get("modelname", ""),
            "uretici": "TP-Link",
            "yazilim": cihaz.get("softwareversion", ""),
        }

    def oku_cihazlar(self) -> list:
        if self.wlan:
            self._istek([(M.OP, "ACT_WLAN_UPDATE_ASSOC", w["__yol"], None, None) for w in self.wlan])
            bagli = self._istek([(M.GS, "LAN_WLAN_ASSOC_DEV", None, w["__yol"], ["AssociatedDeviceMACAddress"])
                                 for w in self.wlan])
        else:
            bagli = []
        self._istek([(M.OP, "ACT_UPDATE_STATS", None, None, None)])
        hostlar, istat = self._istek([(M.GL, "LAN_HOST_ENTRY", None, None, None),
                                      (M.GL, "LAN_HOST_ENTRY_STATS", None, None, None)])

        # hangi cihaz hangi bantta (WLANConfiguration numarası -> bant)
        bant_no = {w["__yol"].split(",")[1]: self._bant(w) for w in self.wlan}
        nerede = {}
        for w, liste in zip(self.wlan, bagli):
            for a in liste:
                nerede.setdefault(a["associateddevicemacaddress"].upper(), []).append(self._bant(w))

        gorulen, sonuc = set(), []
        for i, h in enumerate(hostlar):
            mac = h.get("macaddress", "").upper()
            if not mac or mac in gorulen:
                continue
            gorulen.add(mac)
            s = istat[i] if i < len(istat) else {}
            yuk = int(s.get("x_tt_bytecountuph", 0)) * 2 ** 32 + int(s.get("x_tt_bytecountupl", 0))
            ind = int(s.get("x_tt_bytecountdownh", 0)) * 2 ** 32 + int(s.get("x_tt_bytecountdownl", 0))
            kablo = h.get("interfacetype") == "Ethernet"
            bant = None
            if kablo:
                aktif = h.get("active") == "1"
            else:
                yerler = nerede.get(mac, [])
                aktif = bool(yerler)
                if len(set(yerler)) == 1:
                    bant = yerler[0]
                elif yerler:  # iki listede birden: modemin host kaydındaki arayüze bak
                    m = re.search(r"WLANConfiguration\.(\d+)", h.get("layer2interface", ""))
                    bant = bant_no.get(m.group(1)) if m else yerler[0]
            if not aktif:
                # sayaçlar IP adresine bağlı: aynı IP'yi daha önce almış çevrim dışı kayıt, o IP'nin şimdiki
                # sahibinin sayacını gösterir. Çevrim dışı cihazlara sayaç yazılmaz.
                ind = yuk = 0
            sonuc.append({"mac": mac, "host_adi": h.get("hostname", ""), "ip": h.get("ipaddress", ""), "aktif": aktif,
                          "kablo": kablo, "bant": bant, "indirilen": ind, "yuklenen": yuk,
                          "baglanti": int(s.get("x_tt_staspeed", 0) or 0)})
        return sonuc

    # ---------- engelleme (Wi-Fi MAC filtresi) ----------
    def engelle(self, mac):
        if not self.wlan:
            raise Reddedildi("Açık Wi-Fi ağı bulunamadı.")
        if any(w.get("x_tp_macaddresscontrolrule") != "deny" for w in self.wlan):
            # "allow" kuralında listede olmayan HERKES kopar — panel bu kurala asla dokunmaz
            raise Reddedildi("Modemin MAC filtresi 'yalnız listedekilere izin ver' kipinde; panel bu durumda engelleme yapmaz.")
        for w in self.wlan:
            tablo, = self._istek([(M.GS, "LAN_WLAN_MACTABLEENTRY", None, w["__yol"], ["MACAddress"])])
            if not any(e["macaddress"].upper() == mac for e in tablo):
                self._istek([(M.ADD, "LAN_WLAN_MACTABLEENTRY", None, w["__yol"],
                              {"Enabled": 1, "Description": "panel", "MACAddress": mac, "HostName": w["name"]})])
        t = time.time()
        acildi = False
        for w in self.wlan:
            if w.get("macaddresscontrolenabled") != "1":
                self._istek([(M.SET, "LAN_WLAN", w["__yol"], None, ["MACAddressControlEnabled=1"])])
                acildi = True
        if acildi:
            return f"Engellendi. Filtre ilk kez açıldı, Wi-Fi {time.time() - t:.0f} sn içinde yeniden başladı."
        return "Engellendi."

    def engel_kaldir(self, mac):
        yollar = self.ham["engel"].get(mac, [])
        for y in yollar:
            self._istek([(M.DEL, "LAN_WLAN_MACTABLEENTRY", y, None, None)])
        # filtre açık kalır: kapatmak Wi-Fi'yi yeniden başlatır, boş "engel" listesi kimseyi etkilemez
        return "Engel kaldırıldı." if yollar else "Bu cihaz zaten engelli değildi."

    # ---------- hız sınırı (modemin QoS grupları) ----------
    def _sinif(self, mac):
        return next((c for c in self.ham["sinif"] if c.get("macaddress", "").upper() == mac), None)

    def sinir(self, mac, mbps):
        kbps = int(mbps * 1024)
        sh, gruplar = self.ham["shape"], self.ham["grup"]
        mevcut = self._sinif(mac)
        if mevcut:
            g = next(g for g in gruplar if g.get("id") == mevcut.get("classgroupid"))
            self._istek([(M.SET, "SHAPE_GROUP", g["__yol"], None, {"enable": 1, "upMaxBW": kbps, "downMaxBW": kbps})])
            return f"Sınır {mbps:g} Mbps olarak güncellendi."
        kullanilan = {c.get("classgroupid") for c in self.ham["sinif"]}
        if sh.get("mode") != "1":
            # başka kipte (SSID/IP) açık bir sınır varsa onu bozmayalım
            if any(g.get("enable") == "1" for g in gruplar):
                raise Reddedildi("Modemde başka türden bir hız sınırı tanımlı; panel onu bozmamak için işlem yapmadı.")
        bos = next((g for g in gruplar if g.get("id") not in kullanilan), None)
        if bos is None:
            raise Reddedildi(f"Modem en fazla {GRUP_SAYISI} cihaza sınır koyabiliyor; boş yer kalmadı.")
        if sh.get("mode") != "1":
            self._istek([(M.SET, "SHAPE", sh["__yol"], None, {"mode": 1})])
        self._istek([(M.SET, "SHAPE_GROUP", bos["__yol"], None, {"enable": 1, "upMaxBW": kbps, "downMaxBW": kbps})])
        self._istek([(M.ADD, "SHAPE_CLASS", None, None, {"shapeClassName": "panel", "classGroupId": bos["id"], "enable": 1,
                                                         "mode": 1, "classInterface": "", "MACAddress": mac, "IPAddress": ""})])
        return f"{mbps:g} Mbps sınır kondu."

    def sinir_kaldir(self, mac):
        c = self._sinif(mac)
        if not c:
            return "Bu cihazda sınır yoktu."
        self._istek([(M.DEL, "SHAPE_CLASS", c["__yol"], None, None)])
        g = next((g for g in self.ham["grup"] if g.get("id") == c.get("classgroupid")), None)
        if g:
            self._istek([(M.SET, "SHAPE_GROUP", g["__yol"], None, {"enable": 0})])
        if len(self.ham["sinif"]) == 1:  # son sınır da kalktı: modemi eski kipine döndür
            self._istek([(M.SET, "SHAPE", self.ham["shape"]["__yol"], None, {"mode": 0})])
        return "Sınır kaldırıldı."

    # ---------- sabit IP (DHCP ayırma) ----------
    def sabit(self, mac, ip):
        for s in self.ham["sabit"]:
            if s.get("chaddr", "").upper() == mac:
                self._istek([(M.DEL, "LAN_DHCP_STATIC_ADDR", s["__yol"], None, None)])
        self._istek([(M.ADD, "LAN_DHCP_STATIC_ADDR", None, LAN_YOLU, {"chaddr": mac, "yiaddr": ip, "enable": 1})])
        return f"{ip} bu cihaza sabitlendi."

    def sabit_kaldir(self, mac):
        yollar = [s["__yol"] for s in self.ham["sabit"] if s.get("chaddr", "").upper() == mac]
        for y in yollar:
            self._istek([(M.DEL, "LAN_DHCP_STATIC_ADDR", y, None, None)])
        return "Sabit IP kaldırıldı." if yollar else "Bu cihazda sabit IP yoktu."

    # ---------- interneti durdurma (ebeveyn denetimi) ----------
    def durdurulanlari_yaz(self, macler, koru_mac):
        hepsi = [[True] * 48 for _ in range(7)]
        self._ebeveyn(bool(macler), macler, hepsi, 0, koru_mac)

    def _ebeveyn(self, acik: bool, cihazlar: list, takvim: list, kip: int, ebeveyn_mac: str):
        cihazlar = [m.upper() for m in cihazlar if m][:EBEVEYN_YUVA]
        hostlar, = self._istek([(M.GL, "INTERNAL_HOST", None, None, ["entryName"])])
        yollar = {h.get("entryname"): h["__yol"] for h in hostlar}
        for i in range(EBEVEYN_YUVA):
            yol = yollar.get(f"childMac{i + 1}")
            if yol:
                self._istek([(M.SET, "INTERNAL_HOST", yol, None, [f"mac={cihazlar[i] if i < len(cihazlar) else ''}"])])
        takvimler, = self._istek([(M.GL, "TASK_SCHEDULE", None, None, ["entryName"])])
        tyol = next((t["__yol"] for t in takvimler if t.get("entryname") == "childSchedule1"), "1,0,0,0,0,0")
        self._istek([(M.SET, "TASK_SCHEDULE", tyol, None, takvim_yaz(takvim))])
        self._istek([(M.SET, "FIREWALL", None, None,
                      [f"enalbeParentCtrl={int(acik and bool(cihazlar))}", f"parentMac={ebeveyn_mac if acik and cihazlar else ''}",
                       f"parentCtrlMode={kip}"])])

    # ---------- modem ayarları ----------
    def _wlan_ssid(self):
        wl, = self._istek([(M.GL, "LAN_WLAN", None, None, ["name", "X_TP_Band", "Status", "SSID"])])
        return [w for w in wl if w.get("status") == "Up"]

    def ayar_oku(self) -> dict:
        sonuc = {"wifi": [], "led": None, "ek_ag": None}
        for w in self._wlan_ssid():
            try:
                t, = self._istek([(M.GS, "LAN_WLAN_TASK_SCHEDULE", None, w["__yol"], None)])
                t = t[0] if t else {}
            except Exception:
                t = {}
            sonuc["wifi"].append({
                "yol": w["__yol"], "bant": self._bant(w), "ssid": w.get("ssid", ""),
                "zaman_acik": t.get("enable") == "1", "takvim": takvim_coz(t) if t else None,
            })
        try:
            led, = self._istek([(M.GET, "LED_SCHEDULE", None, None, None)])
            sonuc["led"] = {"acik": led.get("enable") == "1", "baslangic": led.get("starttime") or "22:00",
                            "bitis": led.get("endtime") or "07:00"}
        except Exception:
            pass
        try:
            sonuc["ek_ag"] = self.ek_ag_oku()
        except Exception:
            pass
        return sonuc

    def ek_ag_oku(self):
        v, = self._istek([(M.GL, "LAN_WLAN_MSSIDENTRY", None, None, ["Name", "Enable", "SSID", "IsolateClients", "PreSharedKey"])])
        yuvalar = [x for x in v if x["__yol"].split(",")[2] == "1"]  # her bandın ilk ek ağ yuvası
        if not yuvalar:
            return None
        ilk = yuvalar[0]
        return {"acik": any(x.get("enable") == "1" for x in yuvalar), "ssid": ilk.get("ssid", ""),
                "sifre": ilk.get("presharedkey", ""), "ayirma": ilk.get("isolateclients") == "1",
                "yuvalar": [x["__yol"] for x in yuvalar]}

    def ana_ag(self):
        """QR kodu için ana Wi-Fi'nin adı ve şifresi (yalnız bu bilgisayardaki arayüze gider)."""
        wl, = self._istek([(M.GL, "LAN_WLAN", None, None, ["SSID", "X_TP_Band", "Status", "X_TP_PreSharedKey", "BeaconType"])])
        w = next((w for w in wl if w.get("status") == "Up"), {})
        return {"ssid": w.get("ssid", ""), "sifre": w.get("x_tp_presharedkey", "")}

    def wifi_zaman(self, acik, takvim):
        for w in self._wlan_ssid():
            self._istek([(M.SET, "LAN_WLAN_TASK_SCHEDULE", w["__yol"], None,
                          {"enable": int(acik), "isUsrCtrl": 0, **takvim_yaz(takvim)})])
        return "Wi-Fi zamanlaması kaydedildi." if acik else "Wi-Fi zamanlaması kapatıldı."

    def led(self, acik, baslangic, bitis):
        self._istek([(M.SET, "LED_SCHEDULE", None, None, {"enable": int(acik), "startTime": baslangic, "endTime": bitis})])
        return "Işık zamanlaması kaydedildi." if acik else "Işık zamanlaması kapatıldı."

    def ek_ag(self, acik, ssid, sifre, ayirma):
        bilgi = self.ek_ag_oku()
        if not bilgi:
            raise Reddedildi("Bu modemde ek Wi-Fi ağı yuvası bulunamadı.")
        if acik:
            for yol in bilgi["yuvalar"]:
                self._istek([(M.SET, "LAN_WLAN_MSSIDENTRY", yol, None, [
                    f"IsolateClients={int(ayirma)}", "Enable=1", f"SSID={ssid}", "BeaconType=11i",
                    "IEEE11iAuthenticationMode=PSKAuthentication", "IEEE11iEncryptionModes=AESEncryption",
                    f"PreSharedKey={sifre}"])])
            for w in self._wlan_ssid():
                self._istek([(M.SET, "LAN_WLAN_MULTISSID", w["__yol"], None, ["MultiSSIDEnable=1"])])
            return "Misafir ağı açıldı."
        for yol in bilgi["yuvalar"]:
            self._istek([(M.SET, "LAN_WLAN_MSSIDENTRY", yol, None, ["Enable=0"])])
        return "Misafir ağı kapatıldı."

    def yeniden_baslat(self):
        self._istek([(M.OP, "ACT_REBOOT", None, None, None)])
        return "Modem yeniden başlatılıyor. Yaklaşık 2 dakika internet olmayacak."

    def kayitlar(self) -> list:
        if self.ist is None:
            raise OturumHatasi("oturum yok")
        r = self.ist.oturum.get(self.adres + "/cgi/log", timeout=10)
        satirlar = [s.strip() for s in r.text.splitlines()[1:] if s.strip()]
        return satirlar[-400:]

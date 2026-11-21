"""MikroTik RouterOS 7 — REST API (/rest). DENEYSEL: gerçek bir MikroTik'te denenmedi.

Belgeler: https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST+API · /ip/dhcp-server/lease, /ip/arp,
/interface/wifi (ya da wireless)/registration-table, /ip/firewall/raw, /system/resource, /log.

    Bağlantı   http(s)://<adres>/rest, HTTP Basic kimlik doğrulama, oturum yok. RouterOS 7.1 ve üstü; "www"
               (ya da "www-ssl") servisi açık olmalı. Kendi imzalı sertifika kabul edilir (yalnız yerel ağ).
    Cihazlar   DHCP kiraları + ARP (ağda mı) + Wi-Fi kayıt tablosu (Wi-Fi'de mi, bant, bağlantı hızı).
    Durdurma   /ip/firewall/raw: chain=prerouting src-mac-address=... dst-address-type=!local action=drop
               comment="WaveSnap pause" — bağlantı izlemeden önce düştüğü için açık bağlantılar da hemen kesilir;
               cihaz modemin kendisine (DNS, DHCP) ulaşmaya devam eder.
    Sabit IP   kira statik yapılır ve adresi değiştirilir.

Cihaz başına trafik sayacı yok.
"""
import logging
import re

import requests
import urllib3

from .genel import _gecerli_mac, _mac
from .temel import GirisHatasi, ModemHatasi, OturumHatasi, Reddedildi, Surucu, Yetenek

log = logging.getLogger("panel")
ETIKET = "WaveSnap pause"


def _sure(metin: str) -> int | None:
    """RouterOS süresi ("1w2d03:04:05" ya da "1w2d3h4m5s") -> saniye."""
    if not metin:
        return None
    birim = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
    toplam = sum(int(n) * birim[b] for n, b in re.findall(r"(\d+)([wdhms])", metin))
    saat = re.search(r"(\d+):(\d+):(\d+)$", metin)
    if saat:
        toplam += int(saat[1]) * 3600 + int(saat[2]) * 60 + int(saat[3])
    return toplam


def _bant(*degerler) -> str | None:
    for d in degerler:
        d = str(d or "").lower()
        if "6ghz" in d or re.match(r"(59[3-9]\d|6\d{3}|7[01]\d{2})", d):
            return "6"
        if "5ghz" in d or re.match(r"5\d{3}", d):
            return "5"
        if "2ghz" in d or re.match(r"24\d{2}", d):
            return "2.4"
    return None


class MikroTik(Surucu):
    KIMLIK = "mikrotik"
    AD = "MikroTik RouterOS 7 (deneysel)"
    VARSAYILAN_KULLANICI = "admin"
    KURULUM_NOTU = ("RouterOS 7 gerekir; WaveSnap REST API'yi kullanır (IP > Services'te www ya da www-ssl açık olmalı). "
                    "Bu sürücü henüz gerçek bir MikroTik cihazında denenmedi.")
    GIRIS_GEREKIR = True
    DENEYSEL = True
    TEK_OTURUM = False
    DURDURMA_YUVASI = 0
    yetenekler = frozenset({Yetenek.CIHAZLAR, Yetenek.DURDUR, Yetenek.SABIT_IP, Yetenek.HAT,
                            Yetenek.YENIDEN_BASLAT, Yetenek.KAYITLAR})

    def __init__(self, host: str = "192.168.88.1"):
        super().__init__(host)
        self.taban = None
        self.oturum = None

    @classmethod
    def tani(cls, host):
        """Şifresiz: WebFig giriş sayfası ya da /rest ucunun kimlik isteği RouterOS diyor mu?"""
        for url in (f"http://{host}/", f"http://{host}/rest/system/resource"):
            try:
                r = requests.get(url, timeout=3)
            except requests.RequestException:
                continue
            if "RouterOS" in r.text or "mikrotik" in r.headers.get("WWW-Authenticate", "").lower():
                return True
        return False

    # ---------- oturum ----------
    @property
    def oturum_acik(self):
        return self.oturum is not None

    def giris(self, kullanici, sifre):
        oturum = requests.Session()
        oturum.auth = (kullanici, sifre)
        son = None
        for taban, dogrula in ((f"http://{self.host}/rest", True), (f"https://{self.host}/rest", False)):
            oturum.verify = dogrula
            if not dogrula:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            try:
                r = oturum.get(taban + "/system/resource", timeout=8)
            except requests.RequestException as h:
                son = h
                continue
            if r.status_code == 401:
                raise GirisHatasi("MikroTik kullanıcı adını ya da şifreyi kabul etmedi.")
            if r.ok:
                self.taban, self.oturum = taban, oturum
                return
            son = f"HTTP {r.status_code}"
        raise ModemHatasi(f"MikroTik REST API'sine ulaşılamadı ({son}). IP > Services'te www açık mı?")

    def cikis(self):
        self.oturum = None

    def unut(self):
        self.oturum = None

    def _iste(self, yontem, yol, veri=None):
        if self.oturum is None:
            raise OturumHatasi("oturum yok")
        try:
            r = self.oturum.request(yontem, f"{self.taban}/{yol}", json=veri, timeout=15)
        except requests.RequestException as h:
            raise ModemHatasi(f"MikroTik cevap vermedi ({h}).")
        if r.status_code == 401:
            raise GirisHatasi("MikroTik kullanıcı adını ya da şifreyi kabul etmedi.")
        if r.status_code == 404:
            raise Reddedildi("Bu RouterOS sürümü bu özelliği desteklemiyor.")
        if r.status_code >= 400:
            try:
                j = r.json()
                ayrinti = j.get("detail") or j.get("message") or ""
            except ValueError:
                ayrinti = r.text[:200]
            raise ModemHatasi(f"MikroTik isteği reddetti: {ayrinti}")
        return r.json() if r.content else {}

    # ---------- okuma ----------
    def _wifi(self):
        """{mac: (bant, Mbps)} — yeni 'wifi' paketi, yoksa eski 'wireless'."""
        for paket in ("wifi", "wireless"):
            try:
                kayit = self._iste("GET", f"interface/{paket}/registration-table")
            except (Reddedildi, ModemHatasi):
                continue
            try:
                arayuzler = {a.get("name"): a for a in self._iste("GET", f"interface/{paket}")}
            except (Reddedildi, ModemHatasi):
                arayuzler = {}
            sonuc = {}
            for k in kayit:
                mac = _mac(k.get("mac-address", ""))
                a = arayuzler.get(k.get("interface"), {})
                bant = _bant(k.get("band"), a.get("channel.band"), a.get("band"), a.get("channel.frequency"),
                             a.get("frequency"), a.get("channel"), k.get("interface"))
                hiz = re.match(r"[\d.]+", str(k.get("tx-rate", "")))
                if mac:
                    sonuc[mac] = (bant, round(float(hiz[0])) if hiz else 0)
            return sonuc
        return {}

    def oku_cihazlar(self):
        kiralar = self._iste("GET", "ip/dhcp-server/lease")
        arp = {_mac(a.get("mac-address", "")): a for a in self._iste("GET", "ip/arp") if a.get("mac-address")}
        wifi = self._wifi()
        cihaz = {}
        for k in kiralar:
            mac = _mac(k.get("mac-address", "") or k.get("active-mac-address", ""))
            if mac:
                cihaz[mac] = {"ad": k.get("host-name", "") or k.get("comment", ""), "ip": k.get("active-address") or k.get("address", ""),
                              "bagli": k.get("status") == "bound"}
        onek = self.lan_onek()
        for mac, a in arp.items():
            if a.get("address", "").startswith(onek):
                cihaz.setdefault(mac, {"ad": "", "ip": a.get("address", ""), "bagli": False})
        for mac in wifi:
            cihaz.setdefault(mac, {"ad": "", "ip": "", "bagli": True})
        satirlar = []
        for mac, c in cihaz.items():
            if not _gecerli_mac(mac):
                continue
            a = arp.get(mac, {})
            durum = a.get("status", "")
            aktif = mac in wifi or durum in ("reachable", "delay", "probe") or (bool(a) and durum != "failed" and c["bagli"])
            bant, hiz = wifi.get(mac, (None, 0))
            satirlar.append({"mac": mac, "host_adi": c["ad"], "ip": c["ip"] or a.get("address", ""), "aktif": aktif,
                             "kablo": (mac not in wifi) if aktif else None, "bant": bant,
                             "indirilen": 0, "yuklenen": 0, "baglanti": hiz})
        return satirlar

    def _kurallar(self):
        return [k for k in self._iste("GET", "ip/firewall/raw") if k.get("comment") == ETIKET]

    def oku_ek(self):
        try:
            durdurulan = [_mac(k.get("src-mac-address", "")) for k in self._kurallar() if k.get("src-mac-address")]
        except (ModemHatasi, Reddedildi):
            durdurulan = None
        try:
            sabitler = {_mac(k["mac-address"]): k.get("address", "") for k in self._iste("GET", "ip/dhcp-server/lease")
                        if k.get("dynamic") in ("false", False) and k.get("mac-address")}
        except (ModemHatasi, Reddedildi):
            sabitler = {}
        return {"engelli": set(), "sinirlar": {}, "sabitler": sabitler, "durdurulan": durdurulan, "filtre_acik": False}

    def durdurulanlari_yaz(self, macler, koru_mac):
        istenen = {m.upper() for m in macler if m and m.upper() != (koru_mac or "").upper()}
        var = {}
        for k in self._kurallar():
            mac = _mac(k.get("src-mac-address", ""))
            if mac not in istenen or mac in var:
                self._iste("DELETE", f"ip/firewall/raw/{k['.id']}")
            else:
                var[mac] = k
        for mac in sorted(istenen - set(var)):
            self._iste("PUT", "ip/firewall/raw", {"chain": "prerouting", "src-mac-address": mac,
                                                  "dst-address-type": "!local", "action": "drop", "comment": ETIKET})

    def _kira(self, mac):
        return next((k for k in self._iste("GET", "ip/dhcp-server/lease") if _mac(k.get("mac-address", "")) == mac), None)

    def sabit(self, mac, ip):
        k = self._kira(mac)
        if k is None:
            self._iste("PUT", "ip/dhcp-server/lease", {"mac-address": mac, "address": ip, "comment": "WaveSnap"})
        else:
            if k.get("dynamic") in ("true", True):
                self._iste("POST", "ip/dhcp-server/lease/make-static", {".id": k[".id"]})
            self._iste("PATCH", f"ip/dhcp-server/lease/{k['.id']}", {"address": ip})
        return f"{ip} bu cihaza sabitlendi. Cihaz bir sonraki bağlanışında bu adresi alır."

    def sabit_kaldir(self, mac):
        k = self._kira(mac)
        if not k or k.get("dynamic") in ("true", True):
            return "Bu cihazda sabit IP yoktu."
        self._iste("DELETE", f"ip/dhcp-server/lease/{k['.id']}")
        return "Sabit IP kaldırıldı."

    def oku_hat(self):
        kaynak = self._iste("GET", "system/resource")
        try:
            yollar = self._iste("GET", "ip/route")
            varsayilan = [y for y in yollar if y.get("dst-address") == "0.0.0.0/0"]
            bagli = any(y.get("active") in ("true", True) for y in varsayilan)
        except (ModemHatasi, Reddedildi):
            varsayilan, bagli = [], False
        return {
            "baglanti": "Connected" if bagli else "Disconnected" if varsayilan else "",
            "internet_sure": None,
            "modem_sure": _sure(kaynak.get("uptime", "")),
            "tur": "", "hat_durumu": "",
            "indirme_kbps": 0, "yukleme_kbps": 0, "snr_indirme": 0, "snr_yukleme": 0,
            "model": kaynak.get("board-name", ""), "uretici": "MikroTik",
            "yazilim": "RouterOS " + kaynak.get("version", "") if kaynak.get("version") else "",
        }

    # ---------- modem ayarları ----------
    def yeniden_baslat(self):
        try:
            self._iste("POST", "system/reboot", {})
        except ModemHatasi:
            pass  # modem cevabı vermeden kapanabilir
        return "MikroTik yeniden başlatılıyor. Yaklaşık 1 dakika internet olmayacak."

    def kayitlar(self):
        return [f"{k.get('time', '')} {k.get('topics', '')}: {k.get('message', '')}" for k in self._iste("GET", "log")][-400:]

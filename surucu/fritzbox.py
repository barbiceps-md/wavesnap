"""AVM FRITZ!Box — TR-064 (AVM'nin yayımladığı yönetim arayüzü). DENEYSEL: gerçek bir FRITZ!Box'ta denenmedi.

Belgeler: https://fritz.com/service/schnittstellen/ (hostsSCPD, x_hostfilterSCPD, wlanconfigSCPD, deviceinfoSCPD,
wancommonifconfigSCPD, wandslifconfigSCPD, deviceconfigSCPD).

    Bağlantı      http://<adres>:49000, SOAP, HTTP Digest kimlik doğrulama. Oturum yoktur; her istek kendi
                  kimliğini taşır, FRITZ!Box'ın kendi sayfasıyla aynı anda çalışır.
    Cihazlar      Hosts: X_AVM-DE_GetHostListPath (tek XML, yoksa GetGenericHostEntry tek tek). Wi-Fi bandı
                  WLANConfiguration:N ilişkili cihaz listesinden.
    Durdurma      X_AVM-DE_HostFilter: DisallowWANAccessByIP (IP'ye göre; cihaz sayısı sınırı yok).
    Hat           WANCommonInterfaceConfig, WANDSLInterfaceConfig, WANIPConnection/WANPPPConnection, DeviceInfo.

FRITZ!Box'ta "Heimnetz > Netzwerk > Netzwerkeinstellungen > Zugriff für Anwendungen zulassen" açık olmalı
(varsayılan açık). Cihaz başına trafik sayacı TR-064'te yok.
"""
import logging
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import requests
from requests.auth import HTTPDigestAuth

from .genel import _gecerli_mac, _mac
from .temel import GirisHatasi, ModemHatasi, OturumHatasi, Reddedildi, Surucu, Yetenek

log = logging.getLogger("panel")
PORT = 49000

HOSTS = "urn:dslforum-org:service:Hosts:1"
FILTRE = "urn:dslforum-org:service:X_AVM-DE_HostFilter:1"
CIHAZ = "urn:dslforum-org:service:DeviceInfo:1"
AYAR = "urn:dslforum-org:service:DeviceConfig:1"
WAN_ORTAK = "urn:dslforum-org:service:WANCommonInterfaceConfig:1"
WAN_DSL = "urn:dslforum-org:service:WANDSLInterfaceConfig:1"
WAN_IP = "urn:dslforum-org:service:WANIPConnection:1"
WAN_PPP = "urn:dslforum-org:service:WANPPPConnection:1"
WLAN = "urn:dslforum-org:service:WLANConfiguration:"


def _yerel(etiket: str) -> str:
    return etiket.rsplit("}", 1)[-1]


def _sayi(v, varsayilan=0) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return varsayilan


class FritzBox(Surucu):
    KIMLIK = "fritzbox"
    AD = "AVM FRITZ!Box (deneysel)"
    VARSAYILAN_KULLANICI = ""
    KURULUM_NOTU = ("FRITZ!Box'a girerken kullandığınız kullanıcı adı ve şifre. Kullanıcı adını bilmiyorsanız "
                    "FRITZ!Box'ın giriş sayfasındaki listede görünür. Bu sürücü henüz gerçek bir FRITZ!Box'ta denenmedi.")
    GIRIS_GEREKIR = True
    DENEYSEL = True
    TEK_OTURUM = False
    DURDURMA_YUVASI = 0
    yetenekler = frozenset({Yetenek.CIHAZLAR, Yetenek.DURDUR, Yetenek.HAT, Yetenek.WIFI_QR,
                            Yetenek.YENIDEN_BASLAT, Yetenek.KAYITLAR})

    def __init__(self, host: str = "192.168.178.1"):
        super().__init__(host)
        self.taban = f"http://{host}:{PORT}"
        self.oturum = None
        self.hizmetler = {}     # serviceType -> controlURL
        self.bantlar = None     # WLANConfiguration:N -> "2.4" / "5" / "6"
        self._hostlar = ([], 0.0)

    @classmethod
    def tani(cls, host):
        """Şifresiz: TR-064 cihaz tanımı (tr64desc.xml) üreticisi AVM mi?"""
        try:
            r = requests.get(f"http://{host}:{PORT}/tr64desc.xml", timeout=3)
        except requests.RequestException:
            return False
        return r.ok and "AVM" in r.text and "FRITZ" in r.text.upper()

    # ---------- oturum ----------
    @property
    def oturum_acik(self):
        return self.oturum is not None

    def giris(self, kullanici, sifre):
        oturum = requests.Session()
        oturum.auth = HTTPDigestAuth(kullanici, sifre)
        try:
            r = oturum.get(self.taban + "/tr64desc.xml", timeout=8)
        except requests.RequestException as h:
            raise ModemHatasi(f"FRITZ!Box'a ulaşılamadı ({h}).")
        if not r.ok:
            raise ModemHatasi("FRITZ!Box TR-064 arayüzü kapalı görünüyor.")
        self.hizmetler = {}
        for s in ET.fromstring(r.content).iter():
            if _yerel(s.tag) == "service":
                alan = {_yerel(c.tag): (c.text or "").strip() for c in s}
                if alan.get("serviceType") and alan.get("controlURL"):
                    self.hizmetler[alan["serviceType"]] = alan["controlURL"]
        self.oturum = oturum
        try:
            self._soap(CIHAZ, "GetInfo")  # kimlik doğrulama gerektiren ilk istek: şifre burada sınanır
        except Exception:
            self.oturum = None
            raise
        self.bantlar = None

    def cikis(self):
        self.oturum = None

    def unut(self):
        self.oturum = None

    def _soap(self, tur, eylem, **arg):
        if self.oturum is None:
            raise OturumHatasi("oturum yok")
        url = self.hizmetler.get(tur)
        if not url:
            raise Reddedildi("Bu FRITZ!Box bu özelliği desteklemiyor.")
        govde = ('<?xml version="1.0" encoding="utf-8"?>'
                 '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                 's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                 f'<u:{eylem} xmlns:u="{tur}">'
                 + "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in arg.items())
                 + f"</u:{eylem}></s:Body></s:Envelope>")
        try:
            r = self.oturum.post(self.taban + url, data=govde.encode("utf-8"), timeout=12,
                                 headers={"Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{tur}#{eylem}"'})
        except requests.RequestException as h:
            raise ModemHatasi(f"FRITZ!Box cevap vermedi ({h}).")
        if r.status_code == 401:
            raise GirisHatasi("FRITZ!Box kullanıcı adını ya da şifreyi kabul etmedi.")
        try:
            kok = ET.fromstring(r.content)
        except ET.ParseError:
            raise ModemHatasi(f"FRITZ!Box beklenmeyen cevap verdi (HTTP {r.status_code}).")
        if r.status_code >= 400:
            kod = next((e.text for e in kok.iter() if _yerel(e.tag) == "errorCode"), "?")
            aciklama = next((e.text for e in kok.iter() if _yerel(e.tag) == "errorDescription"), "")
            raise ModemHatasi(f"FRITZ!Box {eylem} reddetti ({kod} {aciklama}).".replace(" )", ")"))
        cevap = next((e for e in kok.iter() if _yerel(e.tag) == eylem + "Response"), None)
        return {_yerel(c.tag): (c.text or "") for c in cevap} if cevap is not None else {}

    def _get(self, yol):
        r = self.oturum.get(self.taban + yol if yol.startswith("/") else yol, timeout=12)
        r.raise_for_status()
        return r.content

    # ---------- okuma ----------
    def _host_listesi(self, en_eski=4.0):
        """Hosts tablosu (alan adları 'New' öneki olmadan); kısa süre önbellekte tutulur."""
        liste, zaman = self._hostlar
        if time.time() - zaman < en_eski:
            return liste
        try:
            yol = self._soap(HOSTS, "X_AVM-DE_GetHostListPath")["NewX_AVM-DE_HostListPath"]
            kok = ET.fromstring(self._get(yol))
            liste = [{_yerel(c.tag): (c.text or "") for c in o} for o in kok.iter() if _yerel(o.tag) == "Item"]
        except (ModemHatasi, KeyError, ET.ParseError, requests.RequestException):
            n = _sayi(self._soap(HOSTS, "GetHostNumberOfEntries").get("NewHostNumberOfEntries"))
            liste = []
            for i in range(n):
                e = self._soap(HOSTS, "GetGenericHostEntry", NewIndex=i)
                liste.append({k[3:] if k.startswith("New") else k: v for k, v in e.items()})
        self._hostlar = (liste, time.time())
        return liste

    def _wlan_bantlari(self):
        if self.bantlar is None:
            self.bantlar = {}
            sira = ["2.4", "5", "6"]
            for n in range(1, 5):
                tur = f"{WLAN}{n}"
                if tur not in self.hizmetler:
                    continue
                try:
                    bilgi = self._soap(tur, "GetInfo")
                except ModemHatasi:
                    continue
                frekans = bilgi.get("NewX_AVM-DE_FrequencyBand", "")
                bant = "5" if frekans.startswith("5") else "6" if frekans.startswith("6") else \
                    "2.4" if frekans.startswith("2") else (sira[n - 1] if n <= 3 else "2.4")
                self.bantlar[tur] = bant
        return self.bantlar

    def _wifi_cihazlari(self):
        """{mac: (bant, Mbps)}"""
        sonuc = {}
        for tur, bant in self._wlan_bantlari().items():
            try:
                n = _sayi(self._soap(tur, "GetTotalAssociations").get("NewTotalAssociations"))
                for i in range(n):
                    a = self._soap(tur, "GetGenericAssociatedDeviceInfo", NewAssociatedDeviceIndex=i)
                    mac = _mac(a.get("NewAssociatedDeviceMACAddress", ""))
                    if mac:
                        sonuc[mac] = (bant, _sayi(a.get("NewX_AVM-DE_Speed")))
            except ModemHatasi:
                log.info("FRITZ!Box: %s ilişkili cihaz listesi okunamadı", tur)
        return sonuc

    def oku_cihazlar(self):
        wifi = self._wifi_cihazlari()
        satirlar = []
        for h in self._host_listesi(en_eski=0):
            mac = _mac(h.get("MACAddress", ""))
            if not _gecerli_mac(mac):
                continue
            aktif = h.get("Active") == "1"
            arayuz = h.get("InterfaceType", "")
            bant, hiz = wifi.get(mac, (None, 0))
            kablo = False if (bant or arayuz == "802.11") else True if arayuz == "Ethernet" else None
            satirlar.append({"mac": mac, "host_adi": h.get("HostName", ""), "ip": h.get("IPAddress", ""),
                             "aktif": aktif, "kablo": kablo, "bant": bant if aktif else None,
                             "indirilen": 0, "yuklenen": 0, "baglanti": hiz or _sayi(h.get("X_AVM-DE_Speed"))})
        return satirlar

    def oku_ek(self):
        durdurulan = []
        try:
            for h in self._host_listesi():
                mac, ip = _mac(h.get("MACAddress", "")), h.get("IPAddress", "")
                if not mac or not ip:
                    continue
                if "X_AVM-DE_Disallow" in h:
                    engelli = h["X_AVM-DE_Disallow"] == "1"
                else:
                    engelli = self._soap(FILTRE, "GetWANAccessByIP", NewIPv4Address=ip).get("NewDisallow") == "1"
                if engelli:
                    durdurulan.append(mac)
        except (ModemHatasi, Reddedildi):
            durdurulan = None
        return {"engelli": set(), "sinirlar": {}, "sabitler": {}, "durdurulan": durdurulan, "filtre_acik": False}

    def durdurulanlari_yaz(self, macler, koru_mac):
        istenen = {m.upper() for m in macler if m and m.upper() != (koru_mac or "").upper()}
        onceki = set(self.oku_ek().get("durdurulan") or [])
        ipler = {_mac(h.get("MACAddress", "")): h.get("IPAddress", "") for h in self._host_listesi(en_eski=0)}
        for mac in istenen ^ onceki:
            ip = ipler.get(mac)
            if not ip:
                log.warning("FRITZ!Box: %s için IP bilinmiyor, durdurma değiştirilemedi", mac)
                continue
            self._soap(FILTRE, "DisallowWANAccessByIP", NewIPv4Address=ip, NewDisallow=int(mac in istenen))
        self._hostlar = ([], 0.0)

    def oku_hat(self):
        sonuc = {"uretici": "AVM"}

        def dene(tur, eylem):
            try:
                return self._soap(tur, eylem)
            except (ModemHatasi, Reddedildi):
                return {}

        cihaz = dene(CIHAZ, "GetInfo")
        sonuc.update(model=cihaz.get("NewModelName", "").replace("AVM ", ""), yazilim=cihaz.get("NewSoftwareVersion", ""),
                     modem_sure=_sayi(cihaz.get("NewUpTime"), None) or None)
        baglanti = dene(WAN_PPP, "GetStatusInfo") or dene(WAN_IP, "GetStatusInfo")
        if baglanti.get("NewConnectionStatus") != "Connected":
            baglanti = dene(WAN_IP, "GetStatusInfo") or baglanti
        sonuc.update(baglanti=baglanti.get("NewConnectionStatus", ""),
                     internet_sure=_sayi(baglanti.get("NewUptime"), None) or None)
        ortak = dene(WAN_ORTAK, "GetCommonLinkProperties")
        dsl = dene(WAN_DSL, "GetInfo") if ortak.get("NewWANAccessType", "DSL") == "DSL" else {}
        sonuc.update(tur=ortak.get("NewWANAccessType", ""),
                     hat_durumu=dsl.get("NewStatus") or ortak.get("NewPhysicalLinkStatus", ""),
                     indirme_kbps=_sayi(dsl.get("NewDownstreamCurrRate")) or _sayi(ortak.get("NewLayer1DownstreamMaxBitRate")) // 1000,
                     yukleme_kbps=_sayi(dsl.get("NewUpstreamCurrRate")) or _sayi(ortak.get("NewLayer1UpstreamMaxBitRate")) // 1000,
                     snr_indirme=_sayi(dsl.get("NewDownstreamNoiseMargin")) / 10,
                     snr_yukleme=_sayi(dsl.get("NewUpstreamNoiseMargin")) / 10)
        return sonuc

    # ---------- modem ayarları ----------
    def ana_ag(self):
        tur = next((t for t, b in self._wlan_bantlari().items()), f"{WLAN}1")
        bilgi = self._soap(tur, "GetInfo")
        anahtar = self._soap(tur, "GetSecurityKeys")
        return {"ssid": bilgi.get("NewSSID", ""), "sifre": anahtar.get("NewKeyPassphrase", "")}

    def yeniden_baslat(self):
        self._soap(AYAR, "Reboot")
        return "FRITZ!Box yeniden başlatılıyor. Birkaç dakika internet olmayacak."

    def kayitlar(self):
        metin = self._soap(CIHAZ, "GetDeviceLog").get("NewDeviceLog", "")
        return [s.strip() for s in metin.splitlines() if s.strip()][:400][::-1]

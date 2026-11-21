"""OpenWrt — ubus JSON-RPC (LuCI'nin kendi kullandığı /ubus ucu). DENEYSEL: gerçek bir OpenWrt'de denenmedi.

Belgeler: https://openwrt.org/docs/techref/ubus · https://openwrt.org/docs/guide-developer/ubus/session
          https://openwrt.org/docs/guide-developer/ubus/iwinfo · LuCI kaynakları (luci-rpc).

    Oturum     session.login (genelde root) -> ubus_rpc_session; 5 dk hareketsizlikte düşer, sürücü yeniden girer.
               Aynı anda birden çok oturum olabilir: LuCI ile çakışmaz.
    Cihazlar   luci-rpc getDHCPLeases + getHostHints (ad, IP), /proc/net/arp (şu an ağda mı),
               iwinfo assoclist (Wi-Fi'de mi, hangi bant, bağlantı hızı).
    Durdurma   güvenlik duvarı kuralı: name "WaveSnap pause", src lan -> dest wan, src_mac, REJECT.
               Kural eklenince yeni bağlantılar kesilir; açık kalan bağlantı kendi kapanana kadar sürebilir.
    Sabit IP   dhcp "host" bölümü (name wavesnap-..., mac, ip).

LuCI kurulu olmalı (uhttpd'nin /ubus ucu onunla gelir). Cihaz başına trafik sayacı yok (nlbwmon gerekir).
"""
import itertools
import logging
import time

import requests

from .genel import _gecerli_mac, _mac
from .temel import GirisHatasi, ModemHatasi, OturumHatasi, Reddedildi, Surucu, Yetenek

log = logging.getLogger("panel")
SIFIR = "0" * 32
ETIKET = "WaveSnap pause"


def _bant(frekans) -> str | None:
    try:
        f = int(frekans)
    except (TypeError, ValueError):
        return None
    return "2.4" if f < 3000 else "5" if f < 5925 else "6"


class OpenWrt(Surucu):
    KIMLIK = "openwrt"
    AD = "OpenWrt (deneysel)"
    VARSAYILAN_KULLANICI = "root"
    KURULUM_NOTU = ("LuCI'ye girerken kullandığınız kullanıcı (genelde root) ve şifresi. LuCI kurulu olmalı. "
                    "Bu sürücü henüz gerçek bir OpenWrt cihazında denenmedi.")
    GIRIS_GEREKIR = True
    DENEYSEL = True
    TEK_OTURUM = False
    DURDURMA_YUVASI = 0
    yetenekler = frozenset({Yetenek.CIHAZLAR, Yetenek.DURDUR, Yetenek.SABIT_IP, Yetenek.HAT, Yetenek.WIFI_QR,
                            Yetenek.YENIDEN_BASLAT, Yetenek.KAYITLAR})

    def __init__(self, host: str = "192.168.1.1"):
        super().__init__(host)
        self.adres = f"http://{host}/ubus"
        self.sid = None
        self._kimlik = None
        self._no = itertools.count(1)

    @classmethod
    def tani(cls, host):
        """Şifresiz: /ubus ucu JSON-RPC konuşuyor mu (oturumsuz 'session access' sorusu)."""
        try:
            r = requests.post(f"http://{host}/ubus", timeout=3, json={
                "jsonrpc": "2.0", "id": 1, "method": "call", "params": [SIFIR, "session", "access", {}]})
            return r.headers.get("Content-Type", "").startswith("application/json") and r.json().get("jsonrpc") == "2.0"
        except (requests.RequestException, ValueError, AttributeError):
            return False

    # ---------- oturum ----------
    @property
    def oturum_acik(self):
        return self.sid is not None

    def _ham(self, sid, nesne, yontem, arg=None):
        try:
            r = requests.post(self.adres, timeout=15, json={
                "jsonrpc": "2.0", "id": next(self._no), "method": "call", "params": [sid, nesne, yontem, arg or {}]})
            j = r.json()
        except requests.RequestException as h:
            raise ModemHatasi(f"OpenWrt cevap vermedi ({h}).")
        except ValueError:
            raise ModemHatasi(f"OpenWrt beklenmeyen cevap verdi (HTTP {r.status_code}).")
        if "error" in j:
            if j["error"].get("code") == -32002:  # Access denied: oturum süresi doldu ya da yetki yok
                raise OturumHatasi(j["error"].get("message", ""))
            raise ModemHatasi(f"ubus {nesne}.{yontem}: {j['error'].get('message')}")
        sonuc = j.get("result") or [0]
        if sonuc[0] == 6:
            raise OturumHatasi("izin yok")
        if sonuc[0] != 0:
            raise ModemHatasi(f"ubus {nesne}.{yontem} hata kodu {sonuc[0]}")
        return sonuc[1] if len(sonuc) > 1 else {}

    def giris(self, kullanici, sifre):
        try:
            cevap = self._ham(SIFIR, "session", "login", {"username": kullanici, "password": sifre})
        except OturumHatasi:
            raise GirisHatasi("OpenWrt kullanıcı adını ya da şifreyi kabul etmedi.")
        self.sid, self._kimlik = cevap.get("ubus_rpc_session"), (kullanici, sifre)
        if not self.sid:
            raise GirisHatasi("OpenWrt oturum açmadı.")

    def cikis(self):
        if self.sid:
            try:
                self._ham(self.sid, "session", "destroy", {"ubus_rpc_session": self.sid})
            except (ModemHatasi, OturumHatasi):
                pass
        self.sid = None

    def unut(self):
        self.sid = None

    def _cagir(self, nesne, yontem, arg=None):
        if self.sid is None:
            raise OturumHatasi("oturum yok")
        try:
            return self._ham(self.sid, nesne, yontem, arg)
        except OturumHatasi:
            if not self._kimlik:
                raise
            log.info("OpenWrt oturumu düşmüştü, yeniden giriliyor")
            self.giris(*self._kimlik)
            return self._ham(self.sid, nesne, yontem, arg)

    def _uci_bolumler(self, config, tur):
        return self._cagir("uci", "get", {"config": config, "type": tur}).get("values", {})

    def _uygula(self, config, servis):
        self._cagir("uci", "commit", {"config": config})
        try:
            self._cagir("rc", "init", {"name": servis, "action": "reload"})
        except (ModemHatasi, OturumHatasi):
            pass  # eski sürümlerde rc nesnesi yok; uci commit zaten yeniden yükleme tetikler

    # ---------- okuma ----------
    def _wifi(self):
        """{mac: (bant, Mbps)}"""
        sonuc = {}
        try:
            aygitlar = self._cagir("iwinfo", "devices").get("devices", [])
        except ModemHatasi:
            return sonuc
        for a in aygitlar:
            try:
                bant = _bant(self._cagir("iwinfo", "info", {"device": a}).get("frequency"))
                for s in self._cagir("iwinfo", "assoclist", {"device": a}).get("results", []):
                    mac = _mac(s.get("mac", ""))
                    if mac:
                        sonuc[mac] = (bant, round((s.get("tx") or {}).get("rate", 0) / 1000))
            except ModemHatasi:
                continue
        return sonuc

    def _arp(self):
        """{mac: ip} — modemin ARP tablosunda şu an tam (flags 0x2) olan LAN kayıtları."""
        try:
            metin = self._cagir("file", "read", {"path": "/proc/net/arp"}).get("data", "")
        except ModemHatasi:
            return None
        onek, sonuc = self.lan_onek(), {}
        for satir in metin.splitlines()[1:]:
            p = satir.split()
            if len(p) >= 4 and p[2] == "0x2" and p[0].startswith(onek):
                sonuc[_mac(p[3])] = p[0]
        return sonuc

    def oku_cihazlar(self):
        kiralar = self._cagir("luci-rpc", "getDHCPLeases").get("dhcp_leases", [])
        ipuclari = self._cagir("luci-rpc", "getHostHints") or {}
        arp, wifi = self._arp(), self._wifi()
        cihaz = {}
        for k in kiralar:
            mac = _mac(k.get("macaddr", ""))
            if mac:
                cihaz[mac] = {"ad": k.get("hostname", ""), "ip": k.get("ipaddr", "")}
        for m, h in ipuclari.items():
            mac = _mac(m)
            if mac and (h.get("ipaddrs") or mac in cihaz):
                c = cihaz.setdefault(mac, {"ad": "", "ip": ""})
                c["ad"] = c["ad"] or h.get("name", "")
                c["ip"] = c["ip"] or (h.get("ipaddrs") or [""])[0]
        for mac, ip in (arp or {}).items():
            cihaz.setdefault(mac, {"ad": "", "ip": ip})
        for mac in wifi:
            cihaz.setdefault(mac, {"ad": "", "ip": ""})
        satirlar = []
        for mac, c in cihaz.items():
            if not _gecerli_mac(mac):
                continue
            bant, hiz = wifi.get(mac, (None, 0))
            # ARP okunamazsa (izin yok) kirası olanları bağlı say
            aktif = mac in wifi or (mac in arp if arp is not None else bool(c["ip"]))
            satirlar.append({"mac": mac, "host_adi": c["ad"], "ip": c["ip"] or (arp or {}).get(mac, ""),
                             "aktif": aktif, "kablo": (mac not in wifi) if aktif else None, "bant": bant,
                             "indirilen": 0, "yuklenen": 0, "baglanti": hiz})
        return satirlar

    def oku_ek(self):
        try:
            kurallar = self._uci_bolumler("firewall", "rule")
            durdurulan = [_mac(k.get("src_mac", "")) for k in kurallar.values() if k.get("name") == ETIKET and k.get("src_mac")]
        except ModemHatasi:
            durdurulan = None
        sabitler = {}
        try:
            for h in self._uci_bolumler("dhcp", "host").values():
                maclar = h.get("mac", [])
                for m in (maclar.split() if isinstance(maclar, str) else maclar):
                    if _mac(m) and h.get("ip"):
                        sabitler[_mac(m)] = h["ip"]
        except ModemHatasi:
            pass
        return {"engelli": set(), "sinirlar": {}, "sabitler": sabitler, "durdurulan": durdurulan, "filtre_acik": False}

    def durdurulanlari_yaz(self, macler, koru_mac):
        istenen = {m.upper() for m in macler if m and m.upper() != (koru_mac or "").upper()}
        for ad, k in self._uci_bolumler("firewall", "rule").items():
            if k.get("name") == ETIKET:
                self._cagir("uci", "delete", {"config": "firewall", "section": ad})
        for mac in sorted(istenen):
            self._cagir("uci", "add", {"config": "firewall", "type": "rule", "values": {
                "name": ETIKET, "src": "lan", "dest": "wan", "src_mac": mac, "proto": "all", "target": "REJECT"}})
        self._uygula("firewall", "firewall")

    def sabit(self, mac, ip):
        self._sabit_sil(mac)
        self._cagir("uci", "add", {"config": "dhcp", "type": "host", "values": {
            "name": "wavesnap-" + mac.replace(":", "").lower(), "mac": mac, "ip": ip}})
        self._uygula("dhcp", "dnsmasq")
        return f"{ip} bu cihaza sabitlendi. Cihaz bir sonraki bağlanışında bu adresi alır."

    def _sabit_sil(self, mac):
        silinen = 0
        for ad, h in self._uci_bolumler("dhcp", "host").items():
            maclar = h.get("mac", [])
            if mac in {_mac(m) for m in (maclar.split() if isinstance(maclar, str) else maclar)}:
                self._cagir("uci", "delete", {"config": "dhcp", "section": ad})
                silinen += 1
        return silinen

    def sabit_kaldir(self, mac):
        if not self._sabit_sil(mac):
            return "Bu cihazda sabit IP yoktu."
        self._uygula("dhcp", "dnsmasq")
        return "Sabit IP kaldırıldı."

    def oku_hat(self):
        kart = self._cagir("system", "board")
        bilgi = self._cagir("system", "info")
        try:
            wan = self._cagir("network.interface.wan", "status")
        except ModemHatasi:
            wan = {}
        return {
            "baglanti": "Connected" if wan.get("up") else "Disconnected" if wan else "",
            "internet_sure": wan.get("uptime") if wan.get("up") else None,
            "modem_sure": bilgi.get("uptime"),
            "tur": (wan.get("proto") or "").upper(),
            "hat_durumu": "Up" if wan.get("up") else "Down" if wan else "",
            "indirme_kbps": 0, "yukleme_kbps": 0, "snr_indirme": 0, "snr_yukleme": 0,
            "model": kart.get("model", ""), "uretici": "",
            "yazilim": (kart.get("release") or {}).get("description", ""),
        }

    # ---------- modem ayarları ----------
    def ana_ag(self):
        for w in self._uci_bolumler("wireless", "wifi-iface").values():
            agi = w.get("network", "")
            if w.get("mode") == "ap" and w.get("disabled") != "1" and "lan" in (agi if isinstance(agi, list) else agi.split()):
                return {"ssid": w.get("ssid", ""), "sifre": w.get("key", "") if w.get("encryption", "none") != "none" else ""}
        raise Reddedildi("Açık bir Wi-Fi ağı bulunamadı.")

    def yeniden_baslat(self):
        self._cagir("system", "reboot")
        return "Modem yeniden başlatılıyor. Yaklaşık 1-2 dakika internet olmayacak."

    def kayitlar(self):
        try:
            satirlar = self._cagir("log", "read", {"lines": 400, "stream": False, "oneshot": True}).get("log", [])
            return [f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s.get('time', 0)))} {s.get('msg', '')}"
                    for s in satirlar]
        except ModemHatasi:
            raise Reddedildi("Bu OpenWrt kayıtları ubus üzerinden vermiyor.")

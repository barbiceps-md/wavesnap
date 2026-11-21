"""Temel mod: her modemde, modem şifresi olmadan.

Ne yapabilir, ne yapamaz (21 Kas 2026, gerçek bir ağda VC220-G3u ile ölçüldü):
  * Cihaz bulma: alt ağdaki her adrese boş bir UDP paketi gönderilir (işletim sistemi bunun için adresin MAC'ini
    sorar), sonra ARP tablosu okunur. Port taraması değildir. Uykudaki telefonlar cevap vermeyebilir: tek turda
    bağlı 4 cihazdan 1'i, iki turla 4'ü bulundu. Arayüz bunu açıkça söyler.
  * Cihaz adı: mDNS (cihazın kendini duyurması) ve ters DNS. Ölçümde 4 cihazdan 2'sinin adı geldi.
  * UPnP'den yalnız modem adı ve "internet bağlı mı" (bkz. oku_hat). Trafik ölçülmez.
  * Engelleme, durdurma, hız sınırı, sabit IP: yok (bunlar için modemin kendi sürücüsü gerekir).
"""
import concurrent.futures as cf
import ipaddress
import logging
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urljoin, urlsplit

from .temel import Surucu, Yetenek

log = logging.getLogger("panel")

TARAMA_ARALIK = 60        # sn
AKTIF_SURE = 10 * 60      # bu kadar süredir görülmeyen cihaz "çevrim dışı" sayılır (uykudaki telefonlar titremesin)
AD_TEKRAR = 30 * 60       # adı bulunamayan cihaz için tekrar deneme
UPNP_TEKRAR = 5 * 60
_GIZLI = 0x08000000 if sys.platform == "win32" else 0  # Windows'ta konsol penceresi açma


def _calistir(komut) -> str:
    try:
        return subprocess.run(komut, capture_output=True, text=True, timeout=10, creationflags=_GIZLI,
                              encoding="utf-8", errors="ignore").stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _mac(m: str) -> str:
    parca = re.split(r"[:-]", m.strip())
    if len(parca) != 6:
        return ""
    try:
        return ":".join(f"{int(p, 16):02X}" for p in parca)
    except ValueError:
        return ""


def _gecerli_mac(mac: str) -> bool:
    if not mac or mac in ("00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"):
        return False
    return not int(mac[:2], 16) & 1  # çok noktaya yayın adresleri değil


def arp_tablosu() -> dict:
    """{ip: mac} — işletim sisteminin ARP önbelleği."""
    sonuc = {}
    if sys.platform.startswith("linux"):
        try:
            for satir in open("/proc/net/arp", encoding="utf-8").read().splitlines()[1:]:
                p = satir.split()
                if len(p) >= 4 and p[2] != "0x0":
                    sonuc[p[0]] = _mac(p[3])
        except OSError:
            pass
    else:
        metin = _calistir(["arp", "-a"] if sys.platform == "win32" else ["arp", "-an"])
        for ip, mac in re.findall(r"\(?(\d+\.\d+\.\d+\.\d+)\)?\s+(?:at\s+)?([0-9A-Fa-f]{1,2}(?:[:-][0-9A-Fa-f]{1,2}){5})", metin):
            sonuc[ip] = _mac(mac)
    return {ip: m for ip, m in sonuc.items() if _gecerli_mac(m)}


def yerel_ip(hedef: str) -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((hedef, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return ""


def yerel_mac(ip: str) -> str:
    """Bu bilgisayarın, verilen IP'yi taşıyan ağ kartının MAC adresi."""
    if sys.platform == "win32":
        for blok in re.split(r"\r?\n\r?\n(?=\S)", _calistir(["ipconfig", "/all"])):
            if re.search(rf"\b{re.escape(ip)}\b", blok):
                m = re.search(r"([0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5})", blok)
                if m:
                    return _mac(m.group(1))
    elif sys.platform.startswith("linux"):
        metin = _calistir(["ip", "-o", "addr"])
        m = re.search(rf"^\d+:\s+(\S+)\s+inet\s+{re.escape(ip)}/", metin, re.M)
        if m:
            try:
                return _mac(open(f"/sys/class/net/{m.group(1)}/address").read())
            except OSError:
                pass
    else:
        metin = _calistir(["ifconfig"])
        for blok in re.split(r"\n(?=\S)", metin):
            if f"inet {ip} " in blok:
                m = re.search(r"ether\s+([0-9a-f:]{17})", blok)
                if m:
                    return _mac(m.group(1))
    import uuid
    n = uuid.getnode()
    return ":".join(f"{(n >> s) & 0xFF:02X}" for s in range(40, -1, -8))


# ---------- mDNS: "bu IP'nin adı ne?" (cihaz kendisi cevaplar) ----------
def _dns_ad(veri, i, derinlik=0):
    parca = []
    while i < len(veri) and derinlik < 10:
        n = veri[i]
        if n == 0:
            return ".".join(parca), i + 1
        if n & 0xC0 == 0xC0:
            ad, _ = _dns_ad(veri, ((n & 0x3F) << 8) | veri[i + 1], derinlik + 1)
            return ".".join(parca + [ad] if ad else parca), i + 2
        parca.append(veri[i + 1:i + 1 + n].decode("utf-8", "ignore"))
        i += 1 + n
    return ".".join(parca), i


def mdns_ad(ip: str, sure=1.2) -> str:
    sorgu_adi = ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
    sorgu = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0) + b"".join(
        bytes([len(p)]) + p.encode() for p in sorgu_adi.split(".")) + b"\0" + struct.pack(">HH", 12, 0x8001)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(sure)
    try:
        s.sendto(sorgu, ("224.0.0.251", 5353))
        bitis = time.time() + sure
        while time.time() < bitis:
            veri, _ = s.recvfrom(4096)
            an, qd = struct.unpack(">H", veri[6:8])[0], struct.unpack(">H", veri[4:6])[0]
            i = 12
            for _ in range(qd):
                _, i = _dns_ad(veri, i)
                i += 4
            for _ in range(an):
                _, i = _dns_ad(veri, i)
                tip, _, _, uz = struct.unpack(">HHIH", veri[i:i + 10])
                i += 10
                if tip == 12:
                    ad = _dns_ad(veri, i)[0]
                    return re.sub(r"\.local\.?$", "", ad)
                i += uz
    except (OSError, struct.error, IndexError):
        pass
    finally:
        s.close()
    return ""


_HAVUZ = cf.ThreadPoolExecutor(4, thread_name_prefix="ad")


def ters_dns(ip: str, sure=2.0) -> str:
    f = _HAVUZ.submit(lambda: socket.gethostbyaddr(ip)[0])
    try:
        ad = f.result(timeout=sure)
        return "" if ad == ip else ad.split(".")[0]
    except Exception:
        return ""


# ---------- UPnP IGD: toplam trafik ve hat ----------
def _soap(url, servis, eylem, sure=4) -> dict:
    govde = (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
             f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:{eylem} xmlns:u="{servis}"/>'
             f'</s:Body></s:Envelope>')
    r = urllib.request.Request(url, govde.encode(), {"Content-Type": 'text/xml; charset="utf-8"',
                                                      "SOAPAction": f'"{servis}#{eylem}"'})
    metin = urllib.request.urlopen(r, timeout=sure).read().decode("utf-8", "ignore")
    return dict(re.findall(r"<(New\w+)>([^<]*)</\1>", metin))


def upnp_bul(host: str, sure=2.5):
    """Modemin UPnP tanımı: {"model", "uretici", "hizmetler": {tür: kontrol_url}} ya da None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(sure)
    yer = None
    try:
        istek = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\n"
                 "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n").encode()
        s.sendto(istek, ("239.255.255.250", 1900))
        bitis = time.time() + sure
        while time.time() < bitis and not yer:
            veri, kim = s.recvfrom(4096)
            if kim[0] != host:
                continue
            m = re.search(r"^LOCATION:\s*(\S+)", veri.decode("utf-8", "ignore"), re.I | re.M)
            if m:
                yer = m.group(1)
    except OSError:
        pass
    finally:
        s.close()
    if not yer or urlsplit(yer).hostname != host:  # yalnız modemin kendisi
        return None
    try:
        xml = urllib.request.urlopen(yer, timeout=4).read().decode("utf-8", "ignore")
    except OSError:
        return None
    taban = (re.search(r"<URLBase>([^<]+)</URLBase>", xml) or [None, yer])[1]
    hizmet = {}
    for tur, kontrol in re.findall(r"<serviceType>([^<]+)</serviceType>.*?<controlURL>([^<]+)</controlURL>", xml, re.S):
        ad = tur.split(":")[-2]
        hizmet.setdefault(ad, (tur, urljoin(taban, kontrol)))
    al = lambda e: (re.search(rf"<{e}>([^<]*)</{e}>", xml) or [None, ""])[1].strip()
    return {"model": al("modelName") or al("friendlyName"), "uretici": al("manufacturer"), "hizmetler": hizmet}


class Genel(Surucu):
    KIMLIK = "genel"
    AD = "Temel mod (her modem, şifresiz)"
    GIRIS_GEREKIR = False
    TEK_OTURUM = False

    def __init__(self, host="192.168.1.1"):
        super().__init__(host)
        self.gorulen = {}         # mac -> {"ip", "son", "ad", "ad_zaman"}
        self.kilit = threading.Lock()
        self.tarama = None
        self.upnp = None
        self.upnp_zaman = 0.0
        self.ben = None           # (ip, mac)

    @property
    def yetenekler(self):
        y = {Yetenek.CIHAZLAR}
        u = self.upnp  # yalnız önceden bulunmuşu kullan; arama tarama iş parçacığında yapılır
        if u and ({"WANIPConnection", "WANPPPConnection"} & set(u["hizmetler"])):
            y.add(Yetenek.HAT)
        return frozenset(y)

    @property
    def oturum_acik(self):
        return True

    def giris(self, kullanici="", sifre=""):
        pass

    # ---------- cihaz bulma ----------
    def _tara(self):
        self._upnp()
        ip = yerel_ip(self.host)
        if not ip:
            return
        if not self.ben or self.ben[0] != ip:
            self.ben = (ip, yerel_mac(ip))
        ag = ipaddress.ip_network(f"{ip}/24", strict=False)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for tur in range(2):
                for h in ag.hosts():
                    try:
                        s.sendto(b"", (str(h), 9))  # discard portu; yalnız ARP sorgusunu tetiklemek için
                    except OSError:
                        pass
                time.sleep(1.5)
        finally:
            s.close()
        simdi = time.time()
        tablo = arp_tablosu()
        tablo[self.ben[0]] = self.ben[1]
        yeniler = []
        with self.kilit:
            for aip, mac in tablo.items():
                if aip == self.host or ipaddress.ip_address(aip) not in ag:
                    continue
                c = self.gorulen.setdefault(mac, {"ad": "", "ad_zaman": 0})
                c["ip"], c["son"] = aip, simdi
                if not c["ad"] and simdi - c["ad_zaman"] > AD_TEKRAR:
                    yeniler.append(mac)
        for mac in yeniler:
            c = self.gorulen[mac]
            ad = socket.gethostname() if c["ip"] == self.ben[0] else (mdns_ad(c["ip"]) or ters_dns(c["ip"]))
            with self.kilit:
                c["ad"], c["ad_zaman"] = ad, time.time()

    def _tarayici(self):
        while True:
            try:
                self._tara()
            except Exception:
                log.exception("cihaz taraması")
            time.sleep(TARAMA_ARALIK)

    def oku_cihazlar(self):
        if self.tarama is None:
            self.tarama = threading.Thread(target=self._tarayici, daemon=True, name="tarama")
            self.tarama.start()
            for _ in range(60):  # ilk taramanın bitmesini kısa süre bekle
                if self.gorulen:
                    break
                time.sleep(0.1)
        simdi = time.time()
        with self.kilit:
            return [{"mac": mac, "host_adi": c["ad"], "ip": c["ip"], "aktif": simdi - c["son"] < AKTIF_SURE,
                     "kablo": None, "bant": None, "indirilen": 0, "yuklenen": 0, "baglanti": 0}
                    for mac, c in self.gorulen.items()]

    # ---------- UPnP ----------
    def _upnp(self):
        if self.upnp is None and time.time() - self.upnp_zaman > UPNP_TEKRAR:
            self.upnp_zaman = time.time()
            self.upnp = upnp_bul(self.host)
        return self.upnp

    def oku_hat(self):
        """UPnP'den yalnız modem adı ve internet bağlı mı. Hat hızı, hat türü, açık kalma süresi ve trafik sayaçları
        kullanılmaz: denenen modemde (TP-Link VC220) hepsi yanlış çıktı (56 yıl açık kalma, 512 kbps hat, 50 MB'lık
        indirmede sayaç 0,1 MB arttı) ve başka modemlerde doğru olup olmadıkları doğrulanamaz."""
        u = self._upnp() or {"hizmetler": {}}
        sonuc = {"model": u.get("model", ""), "uretici": u.get("uretici", "")}
        for ad in ("WANPPPConnection", "WANIPConnection"):
            h = u["hizmetler"].get(ad)
            if not h:
                continue
            try:
                durum = _soap(h[1], h[0], "GetStatusInfo").get("NewConnectionStatus", "")
            except OSError:
                continue
            if durum:
                sonuc["baglanti"] = durum
                if durum == "Connected":
                    break
        return sonuc

"""Deneme için sahte FRITZ!Box (TR-064), OpenWrt (ubus) ve MikroTik (REST) sunucuları.

Her biri belgelerde anlatılan istek/cevap biçimini taklit eder; sürücülerin kodunu (ayrıştırma, oturum, yazma
akışı) modem olmadan sınamak ve demoyu bu markalarla açmak için. Gerçek cihazın her davranışını taklit etmez.

    sunucu, port = baslat("fritzbox", cihazlar)     # cihazlar: [{"mac", "ad", "ip", "kablo", "bant", "aktif"}]
"""
import base64
import hashlib
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

KULLANICI, SIFRE = "admin", "demo"

ORNEK = [
    {"mac": "3C:22:FB:10:20:01", "ad": "MacBook-Air", "ip": "192.168.1.24", "kablo": False, "bant": "5", "aktif": True},
    {"mac": "5A:41:0C:10:20:02", "ad": "Galaxy-S24", "ip": "192.168.1.25", "kablo": False, "bant": "2.4", "aktif": True},
    {"mac": "00:1B:21:10:20:03", "ad": "DESKTOP-7Q2M4LK", "ip": "192.168.1.20", "kablo": True, "bant": None, "aktif": True},
    {"mac": "A8:23:FE:10:20:04", "ad": "LGwebOSTV", "ip": "192.168.1.30", "kablo": True, "bant": None, "aktif": False},
]


class _Temel(BaseHTTPRequestHandler):
    durum = None  # sınıf başına paylaşılan sahte modem durumu

    def log_message(self, *a):
        pass

    def _yaz(self, kod, govde, tur="application/json", basliklar=None):
        veri = govde if isinstance(govde, bytes) else (json.dumps(govde) if not isinstance(govde, str) else govde).encode()
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(veri)))
        for k, v in (basliklar or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(veri)

    def _govde(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""


# --------------------------------------------------------------------------------------------- FRITZ!Box
FRITZ_HIZMETLER = {
    "DeviceInfo:1": "/upnp/control/deviceinfo", "DeviceConfig:1": "/upnp/control/deviceconfig",
    "Hosts:1": "/upnp/control/hosts", "X_AVM-DE_HostFilter:1": "/upnp/control/x_hostfilter",
    "WLANConfiguration:1": "/upnp/control/wlanconfig1", "WLANConfiguration:2": "/upnp/control/wlanconfig2",
    "WANCommonInterfaceConfig:1": "/upnp/control/wancommonifconfig1", "WANDSLInterfaceConfig:1": "/upnp/control/wandslifconfig1",
    "WANPPPConnection:1": "/upnp/control/wanpppconn1", "WANIPConnection:1": "/upnp/control/wanipconnection1",
}
NONCE = "8F1C2D3E4A5B6C7D"


class Fritz(_Temel):
    def _yetkili(self):
        a = self.headers.get("Authorization", "")
        if not a.startswith("Digest "):
            return False
        p = dict(re.findall(r'(\w+)="?([^",]*)"?', a[7:]))
        ha1 = hashlib.md5(f"{KULLANICI}:{p.get('realm')}:{SIFRE}".encode()).hexdigest()
        ha2 = hashlib.md5(f"{self.command}:{p.get('uri')}".encode()).hexdigest()
        if p.get("qop"):
            beklenen = hashlib.md5(f"{ha1}:{p['nonce']}:{p['nc']}:{p['cnonce']}:{p['qop']}:{ha2}".encode()).hexdigest()
        else:
            beklenen = hashlib.md5(f"{ha1}:{p.get('nonce')}:{ha2}".encode()).hexdigest()
        return p.get("username") == KULLANICI and p.get("response") == beklenen

    def _yetki_iste(self):
        self._yaz(401, b"", "text/plain", {"WWW-Authenticate": f'Digest realm="F!Box SOAP-Auth", nonce="{NONCE}", algorithm=MD5, qop="auth"'})

    def do_GET(self):
        if self.path == "/tr64desc.xml":
            hizmet = "".join(f"<service><serviceType>urn:dslforum-org:service:{t}</serviceType><serviceId>x</serviceId>"
                             f"<controlURL>{u}</controlURL><eventSubURL>/x</eventSubURL><SCPDURL>/x.xml</SCPDURL></service>"
                             for t, u in FRITZ_HIZMETLER.items())
            return self._yaz(200, '<?xml version="1.0"?><root xmlns="urn:dslforum-org:device-1-0"><device>'
                             "<manufacturer>AVM Berlin</manufacturer><modelName>FRITZ!Box 7590</modelName>"
                             f"<serviceList>{hizmet}</serviceList></device></root>", "text/xml")
        if self.path.startswith("/devicehostlist.lua"):
            ogeler = "".join(
                f"<Item><Index>{i}</Index><IPAddress>{c['ip']}</IPAddress><MACAddress>{c['mac']}</MACAddress>"
                f"<Active>{int(c['aktif'])}</Active><HostName>{escape(c['ad'])}</HostName>"
                f"<InterfaceType>{'Ethernet' if c['kablo'] else '802.11'}</InterfaceType>"
                f"<X_AVM-DE_Speed>{0 if c['kablo'] else 400}</X_AVM-DE_Speed>"
                f"<X_AVM-DE_Disallow>{int(c['ip'] in self.durum['yasak'])}</X_AVM-DE_Disallow></Item>"
                for i, c in enumerate(self.durum["cihazlar"]))
            return self._yaz(200, f'<?xml version="1.0"?><List><HostNumberOfEntries>{len(self.durum["cihazlar"])}'
                             f"</HostNumberOfEntries>{ogeler}</List>", "text/xml")
        self._yaz(404, b"", "text/plain")

    def do_POST(self):
        govde = self._govde().decode()
        if not self._yetkili():
            return self._yetki_iste()
        eylem = self.headers.get("SOAPAction", "").strip('"').split("#")[-1]
        tur = self.headers.get("SOAPAction", "").strip('"').split("#")[0].rsplit(":", 2)[-2:]
        hizmet = ":".join(tur)
        arg = dict(re.findall(r"<(New\w+)>([^<]*)</\1>", govde))
        d, cev = self.durum, {}
        cihazlar = d["cihazlar"]
        if hizmet.startswith("WLANConfiguration"):
            bant = "2.4" if hizmet.endswith("1") else "5"
            bagli = [c for c in cihazlar if c["aktif"] and not c["kablo"] and c["bant"] == bant]
            if eylem == "GetInfo":
                cev = {"NewEnable": "1", "NewSSID": "FRITZ!Box 7590 XY", "NewX_AVM-DE_FrequencyBand": "2400" if bant == "2.4" else "5000"}
            elif eylem == "GetTotalAssociations":
                cev = {"NewTotalAssociations": len(bagli)}
            elif eylem == "GetGenericAssociatedDeviceInfo":
                c = bagli[int(arg["NewAssociatedDeviceIndex"])]
                cev = {"NewAssociatedDeviceMACAddress": c["mac"], "NewAssociatedDeviceIPAddress": c["ip"], "NewX_AVM-DE_Speed": 866}
            elif eylem == "GetSecurityKeys":
                cev = {"NewKeyPassphrase": "fritz-demo-key"}
        elif eylem == "GetInfo" and hizmet == "DeviceInfo:1":
            cev = {"NewModelName": "FRITZ!Box 7590", "NewSoftwareVersion": "154.07.57", "NewUpTime": 864000}
        elif eylem == "GetDeviceLog":
            cev = {"NewDeviceLog": "21.11.26 10:00:00 Internetverbindung wurde erfolgreich hergestellt.\n21.11.26 09:59:40 DSL ist verfügbar."}
        elif eylem == "Reboot":
            d["yeniden"] += 1
        elif eylem == "X_AVM-DE_GetHostListPath":
            cev = {"NewX_AVM-DE_HostListPath": "/devicehostlist.lua?sid=abc"}
        elif eylem == "GetWANAccessByIP":
            cev = {"NewDisallow": int(arg["NewIPv4Address"] in d["yasak"]), "NewWANAccess": "granted"}
        elif eylem == "DisallowWANAccessByIP":
            (d["yasak"].add if arg["NewDisallow"] == "1" else d["yasak"].discard)(arg["NewIPv4Address"])
        elif eylem == "GetStatusInfo":
            cev = {"NewConnectionStatus": "Connected", "NewUptime": 7200}
        elif eylem == "GetCommonLinkProperties":
            cev = {"NewWANAccessType": "DSL", "NewLayer1DownstreamMaxBitRate": 116000000, "NewLayer1UpstreamMaxBitRate": 40000000,
                   "NewPhysicalLinkStatus": "Up"}
        elif eylem == "GetInfo" and hizmet == "WANDSLInterfaceConfig:1":
            cev = {"NewStatus": "Up", "NewDownstreamCurrRate": 100000, "NewUpstreamCurrRate": 40000,
                   "NewDownstreamNoiseMargin": 90, "NewUpstreamNoiseMargin": 110}
        else:
            return self._yaz(500, '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><s:Fault>'
                             "<detail><UPnPError><errorCode>401</errorCode><errorDescription>Invalid Action</errorDescription>"
                             "</UPnPError></detail></s:Fault></s:Body></s:Envelope>", "text/xml")
        ic = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in cev.items())
        self._yaz(200, f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
                       f'<u:{eylem}Response xmlns:u="urn:dslforum-org:service:{hizmet}">{ic}</u:{eylem}Response></s:Body></s:Envelope>',
                  "text/xml")


# --------------------------------------------------------------------------------------------- OpenWrt
class OpenWrt(_Temel):
    def do_GET(self):
        self._yaz(200, "<html><head><title>OpenWrt - LuCI</title></head></html>", "text/html")

    def do_POST(self):
        if self.path != "/ubus":
            return self._yaz(404, b"", "text/plain")
        istek = json.loads(self._govde() or b"{}")
        sid, nesne, yontem, arg = istek["params"]
        d = self.durum

        def cevap(*sonuc):
            self._yaz(200, {"jsonrpc": "2.0", "id": istek.get("id"), "result": list(sonuc)})

        if nesne == "session" and yontem == "login":
            if arg.get("username") == "root" and arg.get("password") == SIFRE:
                yeni = hashlib.md5(str(time.time()).encode()).hexdigest()
                d["oturumlar"].add(yeni)
                return cevap(0, {"ubus_rpc_session": yeni, "timeout": 300})
            return cevap(6)
        if nesne == "session" and yontem == "access" and sid == "0" * 32:
            return cevap(0, {"access": False})
        if sid not in d["oturumlar"]:
            return self._yaz(200, {"jsonrpc": "2.0", "id": istek.get("id"), "error": {"code": -32002, "message": "Access denied"}})
        cihazlar, uci = d["cihazlar"], d["uci"]
        if (nesne, yontem) == ("session", "destroy"):
            d["oturumlar"].discard(sid)
            return cevap(0)
        if (nesne, yontem) == ("luci-rpc", "getDHCPLeases"):
            return cevap(0, {"dhcp_leases": [{"hostname": c["ad"], "macaddr": c["mac"].lower(), "ipaddr": c["ip"], "expires": 3600}
                                             for c in cihazlar]})
        if (nesne, yontem) == ("luci-rpc", "getHostHints"):
            return cevap(0, {c["mac"].lower(): {"ipaddrs": [c["ip"]], "name": c["ad"]} for c in cihazlar})
        if (nesne, yontem) == ("file", "read") and arg.get("path") == "/proc/net/arp":
            satir = "IP address       HW type     Flags       HW address            Mask     Device\n"
            satir += "".join(f"{c['ip']:<17}0x1         {'0x2' if c['aktif'] else '0x0'}         {c['mac'].lower()}     *        br-lan\n"
                             for c in cihazlar)
            satir += "100.64.0.1       0x1         0x2         00:11:22:33:44:55     *        wan\n"
            return cevap(0, {"data": satir})
        if (nesne, yontem) == ("iwinfo", "devices"):
            return cevap(0, {"devices": ["phy0-ap0", "phy1-ap0"]})
        if (nesne, yontem) == ("iwinfo", "info"):
            return cevap(0, {"frequency": 2437 if arg["device"] == "phy0-ap0" else 5180, "mode": "Master"})
        if (nesne, yontem) == ("iwinfo", "assoclist"):
            bant = "2.4" if arg["device"] == "phy0-ap0" else "5"
            return cevap(0, {"results": [{"mac": c["mac"], "signal": -55, "tx": {"rate": 433300}, "rx": {"rate": 390000}}
                                         for c in cihazlar if c["aktif"] and not c["kablo"] and c["bant"] == bant]})
        if nesne == "uci":
            bolumler = uci.setdefault(arg["config"], {})
            if yontem == "get":
                return cevap(0, {"values": {k: v for k, v in bolumler.items() if v[".type"] == arg.get("type", v[".type"])}})
            if yontem == "add":
                ad = f"cfg{len(bolumler) + 1:04x}{int(time.time() * 1000) % 1000:03d}"
                bolumler[ad] = {".type": arg["type"], ".name": ad, **arg.get("values", {})}
                d["bekleyen"].add(arg["config"])
                return cevap(0, {"section": ad})
            if yontem == "delete":
                bolumler.pop(arg["section"], None)
                d["bekleyen"].add(arg["config"])
                return cevap(0)
            if yontem == "commit":
                d["bekleyen"].discard(arg["config"])
                d["commit"].append(arg["config"])
                return cevap(0)
        if (nesne, yontem) == ("rc", "init"):
            d["yeniden_yukle"].append(arg["name"])
            return cevap(0)
        if (nesne, yontem) == ("system", "board"):
            return cevap(0, {"model": "GL.iNet GL-MT6000", "hostname": "OpenWrt", "release": {"description": "OpenWrt 24.10.4"}})
        if (nesne, yontem) == ("system", "info"):
            return cevap(0, {"uptime": 432000, "localtime": int(time.time())})
        if (nesne, yontem) == ("network.interface.wan", "status"):
            return cevap(0, {"up": True, "uptime": 86400, "proto": "pppoe", "l3_device": "pppoe-wan"})
        if (nesne, yontem) == ("system", "reboot"):
            d["yeniden"] += 1
            return cevap(0)
        if (nesne, yontem) == ("log", "read"):
            return cevap(0, {"log": [{"msg": "daemon.info dnsmasq-dhcp[1]: DHCPACK(br-lan) 192.168.1.24", "time": int(time.time()) - 60}]})
        return cevap(4)  # UBUS_STATUS_NOT_FOUND


# --------------------------------------------------------------------------------------------- MikroTik
class MikroTik(_Temel):
    def _yetkili(self):
        a = self.headers.get("Authorization", "")
        return a == "Basic " + base64.b64encode(f"{KULLANICI}:{SIFRE}".encode()).decode()

    def _isle(self):
        if not self.path.startswith("/rest/"):
            if self.command == "GET":
                return self._yaz(200, "<html><head><title>RouterOS router configuration page</title></head></html>", "text/html")
            return self._yaz(404, b"", "text/plain")
        if not self._yetkili():
            return self._yaz(401, {"error": 401, "message": "Unauthorized"}, basliklar={"WWW-Authenticate": 'Basic realm="mikrotik"'})
        d, yol = self.durum, self.path[len("/rest/"):].split("?")[0]
        govde = json.loads(self._govde() or b"null")
        tablo = lambda ad: d["tablolar"].setdefault(ad, [])  # noqa: E731
        m = re.match(r"(.+)/(\*[0-9A-F]+)$", yol)
        if m and self.command in ("PATCH", "DELETE"):
            satirlar = tablo(m[1])
            k = next((s for s in satirlar if s[".id"] == m[2]), None)
            if k is None:
                return self._yaz(404, {"error": 404, "message": "Not Found"})
            if self.command == "DELETE":
                satirlar.remove(k)
                return self._yaz(204, b"")
            k.update(govde or {})
            return self._yaz(200, k)
        if self.command == "GET":
            if yol == "system/resource":
                return self._yaz(200, {"uptime": "5d03:12:40", "version": "7.16.1 (stable)", "board-name": "hAP ax3",
                                       "platform": "MikroTik"})
            if yol == "ip/dhcp-server/lease":
                return self._yaz(200, d["kiralar"])
            if yol == "ip/arp":
                return self._yaz(200, [{"address": c["ip"], "mac-address": c["mac"], "interface": "bridge",
                                        "status": "reachable" if c["aktif"] else "failed", "dynamic": "true"} for c in d["cihazlar"]])
            if yol == "interface/wifi/registration-table":
                return self._yaz(200, [{"mac-address": c["mac"], "interface": "wifi1" if c["bant"] == "5" else "wifi2",
                                        "tx-rate": "866.7Mbps", "uptime": "1h2m"} for c in d["cihazlar"] if c["aktif"] and not c["kablo"]])
            if yol == "interface/wifi":
                return self._yaz(200, [{"name": "wifi1", "channel.band": "5ghz-ax"}, {"name": "wifi2", "channel.band": "2ghz-ax"}])
            if yol == "ip/route":
                return self._yaz(200, [{"dst-address": "0.0.0.0/0", "gateway": "pppoe-out1", "active": "true"}])
            if yol == "log":
                return self._yaz(200, [{"time": "10:00:00", "topics": "system,info", "message": "router rebooted"}])
            return self._yaz(200, tablo(yol)) if yol in d["tablolar"] else self._yaz(404, {"error": 404, "message": "Not Found"})
        if self.command == "PUT":
            satir = {".id": f"*{len(tablo(yol)) + 100:X}", **govde}
            if yol == "ip/dhcp-server/lease":
                satir["dynamic"] = "false"
                d["kiralar"].append(satir)
            else:
                tablo(yol).append(satir)
            return self._yaz(201, satir)
        if self.command == "POST":
            if yol == "ip/dhcp-server/lease/make-static":
                k = next(k for k in d["kiralar"] if k[".id"] == govde[".id"])
                k["dynamic"] = "false"
                return self._yaz(200, [])
            if yol == "system/reboot":
                d["yeniden"] += 1
                return self._yaz(200, [])
        self._yaz(400, {"error": 400, "message": "Bad Request", "detail": "no such command"})

    do_GET = do_PUT = do_POST = do_PATCH = do_DELETE = _isle


def _mikrotik_durumu(cihazlar):
    kiralar = [{".id": f"*{i + 1:X}", "address": c["ip"], "mac-address": c["mac"], "host-name": c["ad"],
                "status": "bound" if c["aktif"] else "waiting", "dynamic": "true", "server": "defconf"}
               for i, c in enumerate(cihazlar)]
    return {"cihazlar": cihazlar, "kiralar": kiralar, "tablolar": {"ip/firewall/raw": [], "ip/dhcp-server/lease": kiralar},  # kira PATCH/DELETE aynı listeye
            "yeniden": 0}


SINIFLAR = {"fritzbox": Fritz, "openwrt": OpenWrt, "mikrotik": MikroTik}


def baslat(tur: str, cihazlar=None, port: int = 0):
    """Sahte modemi arka planda başlatır; (sunucu, port, durum) döner."""
    cihazlar = [dict(c) for c in (cihazlar or ORNEK)]
    if tur == "fritzbox":
        durum = {"cihazlar": cihazlar, "yasak": set(), "yeniden": 0}
    elif tur == "openwrt":
        durum = {"cihazlar": cihazlar, "oturumlar": set(), "uci": {"firewall": {}, "dhcp": {}, "wireless": {
            "default_radio0": {".type": "wifi-iface", "mode": "ap", "network": "lan", "ssid": "OpenWrt",
                               "encryption": "psk2", "key": "openwrt-demo-key"}}},
            "bekleyen": set(), "commit": [], "yeniden_yukle": [], "yeniden": 0}
    else:
        durum = _mikrotik_durumu(cihazlar)
    sinif = type(f"{tur}_isleyici", (SINIFLAR[tur],), {"durum": durum})
    sunucu = ThreadingHTTPServer(("127.0.0.1", port), sinif)
    sunucu.daemon_threads = True
    threading.Thread(target=sunucu.serve_forever, daemon=True).start()
    return sunucu, sunucu.server_address[1], durum

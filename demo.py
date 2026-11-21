"""WaveSnap demo mode — runs the real panel against a simulated modem with made-up devices.

    python demo.py            full control (a supported router)
    python demo.py --temel    basic mode (any router, no password)
    python demo.py --surucu fritzbox|openwrt|mikrotik   an experimental driver against a simulated router of that brand

No modem, password or network access needed. Everything lives in a throwaway folder that is
wiped on every start, and the panel opens on its own port (8766), so it never touches a real
WaveSnap installation. Use it to try the app or to take screenshots without exposing your network.
"""
import math
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import json
import shutil
from pathlib import Path

KLASOR = Path(__file__).resolve().parent
sys.path.insert(0, str(KLASOR))
PORT = 8766
ADRES = f"http://127.0.0.1:{PORT}/"
DEMO_KOK = Path(tempfile.gettempdir()) / "WaveSnapDemo"
ASIL_ORTAM = dict(os.environ)  # tarayıcı kendi profilini bulsun diye değiştirilmemiş ortam

PC_IP = "192.168.1.20"
SAAT, GUN = 3600, 86400

# ---------------------------------------------------------------------------------------------
# Uydurma cihazlar. MAC'lerin ilk yarısı gerçek üreticilere ait (IEEE listesi), ikinci yarısı rastgele.
# (önek, host adı, ip, arayüz, bant, aktif, kullanıcının verdiği ad, grup, ortalama indirme/yükleme KB/s)
# önek None = telefonların kullandığı gizli (rastgele) MAC
# ---------------------------------------------------------------------------------------------
CIHAZLAR = [
    ("E4C767", "DESKTOP-7Q2M4LK", PC_IP, "kablo", None, True, "Office PC", "", (420, 60)),
    ("34F716", "Deco-M4", "192.168.1.2", "kablo", None, True, "Mesh point", "", (8, 4)),
    (None, "iPhone", "192.168.1.23", "wifi", "5", True, "Emma's iPhone", "Family", (160, 30)),
    ("F0EE7A", "MacBook-Air", "192.168.1.24", "wifi", "5", True, "Daniel's MacBook", "Family", (950, 140)),
    ("AC5AF0", "LGwebOSTV", "192.168.1.30", "wifi", "5", True, "Living room TV", "", (2600, 25)),
    ("F46412", "PS5-1A2B3C", "192.168.1.31", "kablo", None, True, "PlayStation", "", (300, 40)),
    (None, "Galaxy-Tab-A9", "192.168.1.26", "wifi", "5", True, "Kids' tablet", "Family", (520, 20)),
    ("9C7BEF", "HP4A2F1C", "192.168.1.40", "wifi", "2.4", True, "Printer", "", (1, 1)),
    ("D48AFC", "ESP_3A1F2C", "192.168.1.50", "wifi", "2.4", True, "Smart plug", "Smart home", (1, 1)),
    ("842859", "Echo-Dot", "192.168.1.51", "wifi", "2.4", True, "Kitchen speaker", "Smart home", (40, 6)),
    (None, "Galaxy-S24", "192.168.1.25", "wifi", "5", True, "", "", (70, 15)),       # yeni bağlandı
    ("601AC7", "Switch", "192.168.1.32", "wifi", "5", False, "Nintendo Switch", "Family", (0, 0)),
    (None, "", "192.168.1.60", "wifi", "2.4", False, "", "", (0, 0)),               # engellenmiş yabancı
]
YENI = 10       # CIHAZLAR içindeki sıra: son birkaç saatte ilk kez görülen
ENGELLI = 12    # Wi-Fi'den engellenmiş
SINIRLI = 6     # 5 Mbps hız sınırı
SABIT = 7       # sabit IP


def mac_uret(rnd, onek):
    if onek is None:
        ilk = rnd.choice([0x02, 0x06, 0x0A, 0x0E]) | (rnd.randrange(16) << 4)
        bayt = [ilk] + [rnd.randrange(256) for _ in range(5)]
    else:
        bayt = [int(onek[i:i + 2], 16) for i in (0, 2, 4)] + [rnd.randrange(256) for _ in range(3)]
    return ":".join(f"{b:02X}" for b in bayt)


TEMEL = "--temel" in sys.argv
MARKA = sys.argv[sys.argv.index("--surucu") + 1] if "--surucu" in sys.argv else ""
MARKA_PORT = {"fritzbox": 8771, "openwrt": 8772, "mikrotik": 8773}
RND = random.Random(2026)
MACLER = [mac_uret(RND, c[0]) for c in CIHAZLAR]


# ---------------------------------------------------------------------------------------------
# Sahte modem: modem.Modem ile aynı arayüz; TP-Link nesne modelini bellekte taklit eder
# ---------------------------------------------------------------------------------------------
class _Cevap:
    def __init__(self, metin):
        self.text = metin
        self.status_code = 200


class _Oturum:
    def get(self, url, timeout=None):
        simdi = time.time()
        satirlar = ["Index Time Type Level Content"]
        olaylar = [
            (GUN * 3 + 4 * SAAT, "PPP", "Notice", "PPPoE connection established"),
            (GUN * 2, "DHCPD", "Info", f"DHCPACK to 192.168.1.32 ({MACLER[11]})"),
            (SAAT * 5, "WLAN", "Info", f"Station {MACLER[10]} associated on 5GHz"),
            (SAAT * 3, "DHCPD", "Info", f"DHCPACK to 192.168.1.25 ({MACLER[10]})"),
            (SAAT * 2, "WLAN", "Notice", f"Station {MACLER[12]} rejected by MAC filter"),
            (SAAT, "DSL", "Info", "Line rate 104 Mbps / 42 Mbps, SNR 9.5 dB / 8.1 dB"),
            (600, "HTTPD", "Info", "Login from 192.168.1.20"),
        ]
        for i, (once, tur, seviye, metin) in enumerate(olaylar, 1):
            zaman = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(simdi - once))
            satirlar.append(f"{i} {zaman} {tur} {seviye} {metin}")
        return _Cevap("\n".join(satirlar))


class SahteModem:
    GET, SET, ADD, DEL, GL, GS, OP = 1, 2, 3, 4, 5, 6, 7
    BOS = "0,0,0,0,0,0"
    _veri = None
    _kilit = threading.RLock()

    def __init__(self, adres="http://192.168.1.1"):
        self.adres = adres
        self.oturum = _Oturum()
        with SahteModem._kilit:
            if SahteModem._veri is None:
                SahteModem._veri = _baslangic_nesneleri()
                SahteModem._son_istat = time.time()

    def mesgul_mu(self):
        return {"girisli": False}

    def giris(self, kullanici, sifre):
        pass

    def cikis(self):
        pass

    @staticmethod
    def _alanlar(oz):
        if isinstance(oz, dict):
            return {k.lower(): str(v) for k, v in oz.items()}
        sonuc = {}
        for a in oz or []:
            if "=" in a:
                k, v = a.split("=", 1)
                sonuc[k.lower()] = v
        return sonuc

    def istek(self, eylemler):
        sonuc = []
        with SahteModem._kilit:
            v = SahteModem._veri
            for tur, nesne, yol, ust, oz in eylemler:
                liste = v.setdefault(nesne, [])
                if tur == self.GL:
                    sonuc.append([dict(x) for x in liste])
                elif tur == self.GS:
                    sonuc.append([dict(x) for x in liste if x.get("__ust") == ust])
                elif tur == self.GET:
                    x = next((x for x in liste if not yol or x["__yol"] == yol), None)
                    sonuc.append(dict(x) if x else {})
                elif tur == self.SET:
                    x = next((x for x in liste if not yol or x["__yol"] == yol), None)
                    if x is None:
                        x = {"__yol": yol or self.BOS}
                        liste.append(x)
                    x.update(self._alanlar(oz))
                    sonuc.append({})
                elif tur == self.ADD:
                    no = max([int(x["__yol"].split(",")[2]) for x in liste] + [0]) + 1
                    x = {"__yol": f"1,1,{no},0,0,0", "__ust": ust, **self._alanlar(oz)}
                    liste.append(x)
                    sonuc.append(None)
                elif tur == self.DEL:
                    v[nesne] = [x for x in liste if x["__yol"] != yol]
                    sonuc.append(None)
                else:  # OP
                    if nesne == "ACT_UPDATE_STATS":
                        self._trafik_ilerlet()
                    elif nesne == "ACT_WLAN_UPDATE_ASSOC":
                        self._bagli_guncelle()
                    sonuc.append(None)
        return sonuc

    # --- simülasyon ---
    def _bagli_guncelle(self):
        v = SahteModem._veri
        for w in v["LAN_WLAN"]:
            engel = {e["macaddress"].upper() for e in v.get("LAN_WLAN_MACTABLEENTRY", [])
                     if e.get("__ust") == w["__yol"]} if w.get("macaddresscontrolenabled") == "1" else set()
            yeni = []
            for i, c in enumerate(CIHAZLAR):
                if c[3] == "wifi" and c[5] and (c[4] == "5") == ("5" in w["x_tp_band"]) and MACLER[i] not in engel:
                    yeni.append({"__yol": f"{w['__yol'][:4]}{i + 1},0,0,0", "__ust": w["__yol"],
                                 "associateddevicemacaddress": MACLER[i]})
            v["LAN_WLAN_ASSOC_DEV"] = [a for a in v.get("LAN_WLAN_ASSOC_DEV", []) if a["__ust"] != w["__yol"]] + yeni
        for i, h in enumerate(v["LAN_HOST_ENTRY"]):
            if CIHAZLAR[i][3] == "wifi":
                bagli = any(a["associateddevicemacaddress"] == MACLER[i] for a in v["LAN_WLAN_ASSOC_DEV"])
                h["active"] = "1" if bagli else "0"

    def _trafik_ilerlet(self):
        v = SahteModem._veri
        simdi = time.time()
        dt = min(simdi - SahteModem._son_istat, 30)
        SahteModem._son_istat = simdi
        durdurulan = {h.get("mac", "").upper() for h in v.get("INTERNAL_HOST", [])} \
            if v["FIREWALL"][0].get("enalbeparentctrl") == "1" else set()
        sinir = {}
        gruplar = {g["id"]: g for g in v["SHAPE_GROUP"]}
        for s in v.get("SHAPE_CLASS", []):
            g = gruplar.get(s.get("classgroupid"))
            if g and g.get("enable") == "1":
                sinir[s.get("macaddress", "").upper()] = int(g.get("downmaxbw", 0)) * 1024 / 8
        for i, (h, ist) in enumerate(zip(v["LAN_HOST_ENTRY"], v["LAN_HOST_ENTRY_STATS"])):
            if h.get("active") != "1" or MACLER[i] in durdurulan:
                continue
            ind, yuk = CIHAZLAR[i][8]
            dalga = 0.55 + 0.45 * math.sin(simdi / (40 + i * 7) + i) + RND.uniform(-0.25, 0.35)
            ind_bps = max(0.0, ind * 1024 * dalga)
            if MACLER[i] in sinir:
                ind_bps = min(ind_bps, sinir[MACLER[i]] * RND.uniform(0.86, 0.95))
            yuk_bps = max(0.0, yuk * 1024 * dalga)
            for alan, artis in (("down", ind_bps * dt), ("up", yuk_bps * dt)):
                toplam = int(ist[f"x_tt_bytecount{alan}h"]) * 2 ** 32 + int(ist[f"x_tt_bytecount{alan}l"]) + int(artis)
                ist[f"x_tt_bytecount{alan}h"], ist[f"x_tt_bytecount{alan}l"] = str(toplam >> 32), str(toplam & 0xFFFFFFFF)


def _baslangic_nesneleri():
    from surucu.tplink_cgi import takvim_yaz
    kapali = {k.lower(): str(x) for k, x in takvim_yaz([[False] * 48] * 7).items()}
    simdi = time.time()
    wlan = [
        {"__yol": "1,1,0,0,0,0", "name": "wlan0", "x_tp_band": "2.4GHz", "status": "Up", "ssid": "HomeNet",
         "x_tp_presharedkey": "demo-password-123", "beacontype": "11i",
         "macaddresscontrolenabled": "1", "x_tp_macaddresscontrolrule": "deny"},
        {"__yol": "1,2,0,0,0,0", "name": "wlan1", "x_tp_band": "5GHz", "status": "Up", "ssid": "HomeNet",
         "x_tp_presharedkey": "demo-password-123", "beacontype": "11i",
         "macaddresscontrolenabled": "1", "x_tp_macaddresscontrolrule": "deny"},
    ]
    hostlar, istat = [], []
    for i, (_, host, ip, arayuz, bant, aktif, *_r) in enumerate(CIHAZLAR):
        hostlar.append({"__yol": f"1,{i + 1},0,0,0,0", "macaddress": MACLER[i], "hostname": host, "ipaddress": ip,
                        "interfacetype": "Ethernet" if arayuz == "kablo" else "802.11", "active": "1" if aktif else "0",
                        "layer2interface": "" if arayuz == "kablo" else
                        f"InternetGatewayDevice.LANDevice.1.WLANConfiguration.{2 if bant == '5' else 1}"})
        # açılışta sayaçlar: son birkaç günün birikimi gibi
        once = int(CIHAZLAR[i][8][0] * 1024 * 3600 * 6) if aktif else 0
        istat.append({"__yol": f"1,{i + 1},0,0,0,0", "x_tt_bytecountdownh": str(once >> 32),
                      "x_tt_bytecountdownl": str(once & 0xFFFFFFFF), "x_tt_bytecountuph": "0",
                      "x_tt_bytecountupl": str(once // 12 & 0xFFFFFFFF),
                      "x_tt_staspeed": "0" if arayuz == "kablo" else str(RND.choice([866, 780, 650, 433] if bant == "5" else [144, 72, 65]))})
    gruplar = [{"__yol": f"1,{n},0,0,0,0", "id": str(n), "enable": "0", "upmaxbw": "0", "downmaxbw": "0"}
               for n in range(1, 19)]
    gruplar[0].update(enable="1", upmaxbw="5120", downmaxbw="5120")
    return {
        "LAN_WLAN": wlan,
        "LAN_WLAN_MACTABLEENTRY": [{"__yol": "1,1,1,0,0,0", "__ust": w["__yol"], "enabled": "1",
                                    "macaddress": MACLER[ENGELLI], "description": "panel"} for w in wlan[:1]] +
                                  [{"__yol": "1,2,1,0,0,0", "__ust": wlan[1]["__yol"], "enabled": "1",
                                    "macaddress": MACLER[ENGELLI], "description": "panel"}],
        "LAN_WLAN_ASSOC_DEV": [],
        "LAN_WLAN_TASK_SCHEDULE": [{"__yol": w["__yol"], "__ust": w["__yol"], "enable": "0", **kapali} for w in wlan],
        "LAN_WLAN_MSSIDENTRY": [{"__yol": f"1,{b},1,0,0,0", "name": f"ssid{b}1", "enable": "0", "ssid": "HomeNet-Guest",
                                 "presharedkey": "", "isolateclients": "1"} for b in (1, 2)],
        "LAN_WLAN_MULTISSID": [],
        "LAN_HOST_ENTRY": hostlar,
        "LAN_HOST_ENTRY_STATS": istat,
        "SHAPE": [{"__yol": "1,0,0,0,0,0", "mode": "1", "enable": "1"}],
        "SHAPE_GROUP": gruplar,
        "SHAPE_CLASS": [{"__yol": "1,1,1,0,0,0", "shapeclassname": "panel", "classgroupid": "1", "enable": "1",
                         "mode": "1", "macaddress": MACLER[SINIRLI]}],
        "LAN_DHCP_STATIC_ADDR": [{"__yol": "1,1,1,0,0,0", "chaddr": MACLER[SABIT], "yiaddr": CIHAZLAR[SABIT][2],
                                  "enable": "1"}],
        "FIREWALL": [{"__yol": "0,0,0,0,0,0", "enalbeparentctrl": "0", "parentmac": "", "parentctrlmode": "0"}],
        "INTERNAL_HOST": [{"__yol": f"1,{n},0,0,0,0", "entryname": f"childMac{n}", "mac": ""} for n in range(1, 5)],
        "TASK_SCHEDULE": [{"__yol": "1,1,0,0,0,0", "entryname": "childSchedule1", **kapali}],
        "LED_SCHEDULE": [{"__yol": "0,0,0,0,0,0", "enable": "0", "starttime": "22:00", "endtime": "07:00"}],
        "WAN_PPP_CONN": [{"__yol": "1,1,1,0,0,0", "enable": "1", "connectionstatus": "Connected",
                          "uptime": str(int(GUN * 3 + 4 * SAAT)), "lastconnectionerror": "ERROR_NONE"}],
        "WAN_DSL_INTF_CFG": [{"__yol": "1,0,0,0,0,0", "status": "Up", "modulationtype": "VDSL2",
                              "upstreamcurrrate": "42000", "downstreamcurrrate": "104000",
                              "upstreamnoisemargin": "81", "downstreamnoisemargin": "95"}],
        "IGD_DEV_INFO": [{"__yol": "0,0,0,0,0,0", "modelname": "VC220-G3u", "softwareversion": "Demo",
                          "uptime": str(int(GUN * 12 + 7 * SAAT))}],
    }


# ---------------------------------------------------------------------------------------------
# Demo klasörü: cihaz adları ve geçmiş (kullanım, olaylar, kesintiler, hız testleri) önceden doldurulur
# ---------------------------------------------------------------------------------------------
def demo_klasoru_hazirla():
    shutil.rmtree(DEMO_KOK, ignore_errors=True)
    veri = DEMO_KOK
    veri.mkdir(parents=True)
    simdi = int(time.time())
    cihazlar = {}
    for i, (_, host, ip, arayuz, bant, aktif, ad, grup, _h) in enumerate(CIHAZLAR):
        c = {"ilk": simdi - GUN * (40 - i), "tohum": True, "host_adi": host, "ip": ip,
             "bant": "kablo" if arayuz == "kablo" else bant, "son": simdi if aktif else simdi - GUN * 2 - 5 * SAAT}
        if ad:
            c["ad"] = ad
        if grup:
            c["grup"] = grup
        cihazlar[MACLER[i]] = c
    cihazlar[MACLER[YENI]].update(ilk=simdi - 3 * SAAT, tohum=False)
    cihazlar[MACLER[9]]["cins"] = "akilli"
    cihazlar[MACLER[ENGELLI]]["not"] = "Tried to join the Wi-Fi at night."
    for i in (0, 1, 2, 3):
        cihazlar[MACLER[i]]["guvenilir"] = True
    gece = [[(s >= 44 or s < 14) for s in range(48)] for _ in range(7)]  # 22:00–07:00 internet kapalı
    ayar = {"bildirim": False, "dil": "en", "tema": "storm", "takvimler": {MACLER[SINIRLI]: gece},
            "surucu": "genel" if TEMEL else MARKA or "tplink_cgi",
            "modem_adres": "127.0.0.1" if MARKA == "fritzbox" else f"127.0.0.1:{MARKA_PORT[MARKA]}" if MARKA else "192.168.1.1"}
    (veri / "cihazlar.json").write_text(json.dumps({"cihazlar": cihazlar, "ayar": ayar}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    return veri


def gecmisi_doldur(g):
    rnd = random.Random(7)
    simdi = time.time()
    bu_saat = int(simdi // SAAT * SAAT)
    satirlar = []
    for i, c in enumerate(CIHAZLAR):
        ind, yuk = c[8]
        if not c[5]:
            ind, yuk = (380, 30) if i == 11 else (0, 0)
        for s in range(30 * 24):
            saat = bu_saat - s * SAAT
            if i == YENI and s > 3:
                break
            yerel = time.localtime(saat).tm_hour
            gunluk = 0.15 + (1.0 if 18 <= yerel <= 23 else 0.55 if 8 <= yerel < 18 else 0.1)
            if rnd.random() < 0.25:
                continue
            carpan = gunluk * rnd.uniform(0.3, 1.6) * 3600
            if ind * carpan > 0:
                satirlar.append((MACLER[i], saat, int(ind * 1024 * carpan * 0.35), int(yuk * 1024 * carpan * 0.35)))
    with g.kilit:
        g.db.executemany("INSERT OR REPLACE INTO kullanim VALUES (?, ?, ?, ?)", satirlar)
        olay = []
        for gun in range(6, -1, -1):
            for i in (2, 3, 6, 10, 11):
                if i == YENI and gun:
                    continue
                gel = simdi - gun * GUN - rnd.randint(2, 12) * SAAT
                if gel < simdi - 60:
                    olay.append((int(gel), MACLER[i], "geldi", CIHAZLAR[i][2]))
                git = gel + rnd.randint(1, 6) * SAAT
                if git < simdi - 600 and (gun or not CIHAZLAR[i][5]):
                    olay.append((int(git), MACLER[i], "gitti", CIHAZLAR[i][2]))
        olay.append((int(simdi - 3 * SAAT), MACLER[YENI], "yeni", CIHAZLAR[YENI][2]))
        olay.append((int(simdi - 2 * SAAT), MACLER[ENGELLI], "yeni", CIHAZLAR[ENGELLI][2]))
        olay.append((int(simdi - 3 * GUN - 4 * SAAT), "", "yeniden_baglandi", "Modemin internet bağlantısı yeniden kuruldu"))
        g.db.executemany("INSERT INTO olay VALUES (?, ?, ?, ?)", olay)
        g.db.executemany("INSERT INTO kesinti (baslangic, bitis, tur) VALUES (?, ?, ?)", [
            (int(simdi - 3 * GUN - 4 * SAAT - 140), int(simdi - 3 * GUN - 4 * SAAT), "internet"),
            (int(simdi - 9 * GUN - 2 * SAAT), int(simdi - 9 * GUN - 2 * SAAT + 45), "ag"),
        ])
        g.db.executemany("INSERT INTO hiz_testi VALUES (?, ?, ?, ?)", [
            (int(simdi - d * GUN - rnd.randint(1, 8) * SAAT), round(rnd.uniform(86, 97), 1), round(rnd.uniform(36, 40), 1),
             round(rnd.uniform(11, 18), 1)) for d in (1, 3, 6, 10, 14)])
        dakika = int(simdi // 60 * 60)
        trafik = []
        for d in range(24 * 60, 0, -1):
            z = dakika - d * 60
            yerel = time.localtime(z).tm_hour
            taban = 28e6 if 18 <= yerel <= 23 else 12e6 if 8 <= yerel < 18 else 2e6  # bit/sn
            trafik.append((z, int(taban * rnd.uniform(0.5, 1.6)), int(taban * 0.08 * rnd.uniform(0.5, 1.8))))
        g.db.executemany("INSERT OR REPLACE INTO trafik_dk VALUES (?, ?, ?)", trafik)
        g.db.commit()


def sahte_hiz_testi(ilerleme=None):
    ilerle = ilerleme or (lambda *_: None)
    ilerle("gecikme", 0)
    time.sleep(1.2)
    hedef = (RND.uniform(88, 96), RND.uniform(36, 40))
    for asama, son in (("indirme", hedef[0]), ("yukleme", hedef[1])):
        for k in range(1, 21):
            ilerle(asama, son * (1 - math.exp(-k / 5)) * RND.uniform(0.97, 1.03))
            time.sleep(0.15)
    return {"indirme": round(hedef[0], 1), "yukleme": round(hedef[1], 1), "gecikme": round(RND.uniform(12, 16), 1)}


def calisiyor():
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.5).close()
        return True
    except OSError:
        return False


def pencere_ac():
    if "--pencere-yok" in sys.argv:
        print("WaveSnap demo:", ADRES)
        return
    import sistem
    sistem.pencere_ac(ADRES, ASIL_ORTAM)


def main():
    if calisiyor():
        pencere_ac()
        return
    demo_klasoru_hazirla()
    os.environ["WAVESNAP_VERI"] = str(DEMO_KOK)  # depo, geçmiş ve şifre kasası demo klasörüne yazar
    os.chdir(KLASOR)

    import bildirim
    import izleyici
    import servis
    import sifre_kasasi
    import surucu.genel
    import surucu.tplink_cgi

    surucu.tplink_cgi.Istemci = SahteModem

    def sahte_tarama(self):
        """Temel mod: ağ taraması yerine uydurma cihazlar. Uykudaki iPhone ve Switch görünmez; adların bir kısmı gelmez."""
        simdi = time.time()
        with self.kilit:
            for i, c in enumerate(CIHAZLAR):
                if c[5] and i not in (2, ENGELLI):
                    self.gorulen[MACLER[i]] = {"ip": c[2], "son": simdi, "ad": c[1] if i % 3 else "", "ad_zaman": simdi}
            self.upnp = {"model": "VC220-G3u", "uretici": "TP-Link", "hizmetler": {}}
    surucu.genel.Genel._tara = sahte_tarama
    servis.bu_pc_ip = lambda *a: PC_IP
    sifre_kasasi.var_mi = lambda: True
    sifre_kasasi.oku = lambda: ("root" if MARKA == "openwrt" else "admin", "demo")
    if MARKA:  # deneysel sürücü + o markanın sahte modemi (araclar/sahte_yonlendiriciler.py)
        sys.path.insert(0, str(KLASOR / "araclar"))
        import sahte_yonlendiriciler
        import surucu.fritzbox
        sahte_yonlendiriciler.baslat(MARKA, [{"mac": MACLER[i], "ad": c[1], "ip": c[2], "kablo": c[3] == "kablo", "bant": c[4],
                                              "aktif": c[5]} for i, c in enumerate(CIHAZLAR)], MARKA_PORT[MARKA])
        surucu.fritzbox.PORT = MARKA_PORT["fritzbox"]
        for s in surucu.SURUCULER.values():
            s.lan_onek = lambda self: "192.168.1."  # sahte modem 127.0.0.1'de, cihazlar 192.168.1.x
    import surucu.kesif

    def sahte_kesif(adres=""):
        """Kurulum ekranı gerçek ağı değil demo modemini 'bulur'."""
        kimlik = "genel" if TEMEL else MARKA or "tplink_cgi"
        return {"adres": adres or ("127.0.0.1" if MARKA else "192.168.1.1"),
                "model": {"tplink_cgi": "TP-Link VC220-G3u", "fritzbox": "AVM FRITZ!Box 7590", "openwrt": "GL.iNet GL-MT6000",
                          "mikrotik": "MikroTik hAP ax3"}.get(kimlik, ""),
                "surucu": kimlik, "surucu_ad": surucu.SURUCULER[kimlik].AD, "tanindi": kimlik != "genel", "upnp": True,
                "secenekler": surucu.kesif.secenekler()}
    surucu.kesif.tani = sahte_kesif
    bildirim.gonder = lambda *a, **k: None
    izleyici.ulasir = lambda *a, **k: True
    izleyici.KesintiIzleyici.calis = lambda self: setattr(self, "durum", "var")
    izleyici.hiz_testi = sahte_hiz_testi

    import sunucu
    sunucu.PORT = PORT
    sunucu.IZINLI_HOST = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
    gecmisi_doldur(sunucu.panel.gecmis)
    # canlı trafik grafiği boş başlamasın: son 30 dakika
    simdi = time.time()
    for k in range(450, 0, -1):
        z = simdi - k * 4
        dalga = 1 + 0.35 * math.sin(z / 170) + 0.2 * math.sin(z / 37)
        sunucu.panel.trafik.append((round(z, 1), int(14e6 * dalga * RND.uniform(0.8, 1.2)), int(1.3e6 * dalga * RND.uniform(0.6, 1.4))))

    def bekle_ve_ac():
        for _ in range(50):
            if calisiyor():
                break
            time.sleep(0.1)
        pencere_ac()

    sunucu.panel.kalp()
    threading.Thread(target=bekle_ve_ac, daemon=True).start()
    sunucu.calistir()


if __name__ == "__main__":
    main()

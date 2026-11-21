"""Hızlı deneme (her işletim sisteminde, kaynaktan ya da CI'da): modem gerekmez.

1. Ağ yardımcıları bu işletim sisteminin komutlarıyla çökmeden çalışıyor mu (ağ geçidi, ARP tablosu, yerel IP/MAC).
2. Şifre kasası: kaydet → oku → sil (geçici klasörde).
3. Demo sunucusu (tam mod ve temel mod): cihaz listesi geliyor mu, bir işlem çalışıyor mu, düzgün kapanıyor mu.

    python araclar/duman_testi.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
DEMO = "http://127.0.0.1:8766"
hatalar = []


def kontrol(kosul, mesaj):
    print(("  ok    " if kosul else "  HATA  ") + mesaj)
    if not kosul:
        hatalar.append(mesaj)


def istek(yol, govde=None):
    r = urllib.request.Request(DEMO + yol, json.dumps(govde).encode() if govde is not None else None,
                               {"X-Panel": "1", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=30))


print("1. ağ yardımcıları —", sys.platform)
from surucu import genel, kesif  # noqa: E402

gecit = kesif.ag_gecidi()
print("  ağ geçidi:", gecit or "(yok)")
arp = genel.arp_tablosu()
print("  ARP tablosu:", len(arp), "kayıt")
ip = genel.yerel_ip(gecit or "1.1.1.1")
print("  yerel IP:", ip or "(yok)", "· MAC:", genel.yerel_mac(ip) if ip else "-")
kontrol(isinstance(arp, dict), "ARP tablosu okunabildi")

print("2. şifre kasası")
with tempfile.TemporaryDirectory() as gecici:
    kod = ("import sifre_kasasi as k; k.kaydet('admin', 'p@ss şifre'); assert k.var_mi(); "
           "assert k.oku() == ('admin', 'p@ss şifre'), k.oku(); k.sil(); assert not k.var_mi(); print('  ok    kaydet/oku/sil')")
    r = subprocess.run([sys.executable, "-c", kod], cwd=KOK, env={**os.environ, "WAVESNAP_VERI": gecici},
                       capture_output=True, text=True, encoding="utf-8")
    print(r.stdout.rstrip() or r.stderr.strip()[-600:])
    if r.returncode:
        hatalar.append("şifre kasası")

for ad, ek in (("tam mod", []), ("temel mod", ["--temel"])):
    print(f"3. demo — {ad}")
    islem = subprocess.Popen([sys.executable, str(KOK / "demo.py"), "--pencere-yok", *ek], cwd=KOK,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        v = None
        for _ in range(90):
            try:
                v = istek("/api/durum")
                if v.get("durum") == "canli" and v.get("cihazlar"):
                    break
            except OSError:
                pass
            time.sleep(1)
        kontrol(bool(v and v.get("cihazlar")), f"cihaz listesi geldi ({len(v['cihazlar']) if v else 0})")
        if v and v.get("cihazlar"):
            kontrol(v["surucu"]["kimlik"] == ("genel" if ek else "tplink_cgi"), f"sürücü {v['surucu']['kimlik']}")
            mac = v["cihazlar"][0]["mac"]
            r = istek("/api/islem", {"islem": "adlandir", "mac": mac, "ad": "Deneme"})
            kontrol("sonuc" in r, "adlandırma işlemi")
            if not ek:
                hedef = next(c for c in v["cihazlar"] if c["aktif"] and not c["bu_pc"])
                r = istek("/api/islem", {"islem": "sinir", "mac": hedef["mac"], "mbps": 5})
                kontrol("sonuc" in r, "hız sınırı işlemi")
        istek("/api/kapat", {})
        islem.wait(timeout=20)
        kontrol(True, "düzgün kapandı")
    except Exception as e:
        kontrol(False, f"{type(e).__name__}: {e}")
        islem.kill()
        print(islem.stderr.read()[-2000:] if islem.stderr else "")

print("SONUÇ:", "tamam" if not hatalar else f"{len(hatalar)} hata")
sys.exit(1 if hatalar else 0)

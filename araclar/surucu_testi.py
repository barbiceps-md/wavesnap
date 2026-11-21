"""Deneysel sürücüleri (FRITZ!Box, OpenWrt, MikroTik) sahte modemlere karşı sınar. Modem gerekmez.

    python araclar/surucu_testi.py

Sınananlar: tanıma (kendi sahtesini tanır, ötekileri tanımaz), yanlış şifre, giriş, cihaz listesi (bağlı/değil,
kablo/Wi-Fi, bant), interneti durdurma ve geri alma, sabit IP, hat bilgisi, kayıtlar, Wi-Fi adı/şifresi,
oturum düşünce yeniden giriş (OpenWrt).
"""
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(KOK / "araclar"))

import sahte_yonlendiriciler as sahte  # noqa: E402
import surucu.fritzbox  # noqa: E402
from surucu import FritzBox, GirisHatasi, MikroTik, OpenWrt, Yetenek  # noqa: E402

hatalar = []


def kontrol(kosul, mesaj):
    print(("  ok    " if kosul else "  HATA  ") + mesaj)
    if not kosul:
        hatalar.append(mesaj)


sunucular = {tur: sahte.baslat(tur) for tur in ("fritzbox", "openwrt", "mikrotik")}
SINIF = {"fritzbox": FritzBox, "openwrt": OpenWrt, "mikrotik": MikroTik}
KULLANICI = {"fritzbox": "admin", "openwrt": "root", "mikrotik": "admin"}
beklenen = {c["mac"]: c for c in sahte.ORNEK}


def surucu_kur(tur):
    _, port, _ = sunucular[tur]
    if tur == "fritzbox":
        surucu.fritzbox.PORT = port
        return FritzBox("127.0.0.1")
    return SINIF[tur](f"127.0.0.1:{port}")


for tur, sinif in SINIF.items():
    print(f"{sinif.AD}")
    _, port, durum = sunucular[tur]
    surucu.fritzbox.PORT = sunucular["fritzbox"][1] if tur == "fritzbox" else 1  # FRITZ tanıması başka portta yanılmasın
    adres = "127.0.0.1" if tur == "fritzbox" else f"127.0.0.1:{port}"
    kontrol(sinif.tani(adres), "kendi modemini tanıdı")
    yabanci = [s.AD for t, s in SINIF.items() if t != tur and s.tani(adres)]
    kontrol(not yabanci, "başka sürücüler tanımadı" + (f" (tanıyan: {yabanci})" if yabanci else ""))

    d = surucu_kur(tur)
    d.lan_onek = lambda: "192.168.1."
    try:
        d.giris(KULLANICI[tur], "yanlis")
        kontrol(False, "yanlış şifre reddedildi")
    except GirisHatasi:
        kontrol(True, "yanlış şifre reddedildi")
    d.giris(KULLANICI[tur], sahte.SIFRE)
    kontrol(d.oturum_acik, "giriş yapıldı")

    satirlar = {r["mac"]: r for r in d.oku_cihazlar()}
    kontrol(set(satirlar) == set(beklenen), f"cihaz listesi ({len(satirlar)}/{len(beklenen)})")
    for mac, c in beklenen.items():
        r = satirlar.get(mac, {})
        dogru = r.get("aktif") == c["aktif"] and (not c["aktif"] or (r.get("kablo") == c["kablo"] and r.get("bant") == c["bant"]))
        kontrol(dogru and r.get("ip") == c["ip"], f"{c['ad']}: bağlı={r.get('aktif')} kablo={r.get('kablo')} bant={r.get('bant')} ip={r.get('ip')}")

    ek = d.oku_ek()
    kontrol(ek["durdurulan"] == [], "başta durdurulan yok")
    hedef = ["3C:22:FB:10:20:01", "5A:41:0C:10:20:02"]
    d.durdurulanlari_yaz(hedef + ["00:1B:21:10:20:03"], "00:1B:21:10:20:03")
    kontrol(sorted(d.oku_ek()["durdurulan"]) == sorted(hedef), "iki cihaz durduruldu, bu bilgisayar korundu")
    d.durdurulanlari_yaz(hedef[:1], "")
    kontrol(d.oku_ek()["durdurulan"] == hedef[:1], "biri devam ettirildi")
    d.durdurulanlari_yaz([], "")
    kontrol(d.oku_ek()["durdurulan"] == [], "hepsi serbest")

    if Yetenek.SABIT_IP in d.yetenekler:
        d.sabit("5A:41:0C:10:20:02", "192.168.1.60")
        kontrol(d.oku_ek()["sabitler"].get("5A:41:0C:10:20:02") == "192.168.1.60", "sabit IP yazıldı")
        d.sabit("5A:41:0C:10:20:02", "192.168.1.61")
        kontrol(d.oku_ek()["sabitler"].get("5A:41:0C:10:20:02") == "192.168.1.61", "sabit IP değiştirildi (tek kayıt)")
        d.sabit_kaldir("5A:41:0C:10:20:02")
        kontrol("5A:41:0C:10:20:02" not in d.oku_ek()["sabitler"], "sabit IP kaldırıldı")

    hat = d.oku_hat()
    kontrol(hat.get("model") and hat.get("baglanti") in ("Connected", ""), f"hat: {hat.get('uretici')} {hat.get('model')} · {hat.get('baglanti')} · {hat.get('yazilim')}")
    kontrol(len(d.kayitlar()) > 0, "kayıtlar okundu")
    if Yetenek.WIFI_QR in d.yetenekler:
        ag = d.ana_ag()
        kontrol(bool(ag.get("ssid") and ag.get("sifre")), f"Wi-Fi adı ve şifresi ({ag.get('ssid')})")
    d.yeniden_baslat()
    kontrol(durum["yeniden"] == 1, "yeniden başlatma isteği gitti")

    if tur == "openwrt":
        durum["oturumlar"].clear()  # modem oturumu düşürdü (5 dk hareketsizlik)
        kontrol(len(d.oku_cihazlar()) == len(beklenen), "oturum düşünce kendiliğinden yeniden girdi")
        kontrol(not durum["bekleyen"], "uci değişikliklerinin hepsi kaydedildi (commit)")
    d.cikis()

print("SONUÇ:", "tamam" if not hatalar else f"{len(hatalar)} hata")
sys.exit(1 if hatalar else 0)

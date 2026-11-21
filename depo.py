"""Panelin kendi kayıtları: cihaz adları, ilk/son görülme, ayarlar.

<veri klasörü>/cihazlar.json (sistem.VERI) — şifre burada DEĞİL (o sifre_kasasi'nda).
"""
import json
import os
import threading
import time

import sistem

KLASOR = sistem.VERI
DOSYA = KLASOR / "cihazlar.json"


class Depo:
    def __init__(self):
        self.kilit = threading.Lock()
        self.ilk_kurulum = not DOSYA.exists()
        self.veri = {"cihazlar": {}, "ayar": {"bildirim": True}}
        if not self.ilk_kurulum:
            try:
                self.veri.update(json.loads(DOSYA.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
            self.ayar.setdefault("dil", "tr")  # dil seçimi gelmeden önce kurulmuş (Türkçe) panel
        else:
            self.ayar["dil"] = "en"            # ilk kurulum: İngilizce, sonra Ayarlar'dan değişir
        self.kirli = False

    @property
    def cihazlar(self) -> dict:
        return self.veri["cihazlar"]

    @property
    def ayar(self) -> dict:
        return self.veri["ayar"]

    def gor(self, mac, host_adi, ip, bant, aktif) -> bool:
        """Cihazı kaydeder. Daha önce hiç görülmemiş bir cihazsa True döner."""
        with self.kilit:
            c = self.cihazlar.get(mac)
            simdi = int(time.time())
            yeni = c is None
            if yeni:
                # ilk açılışta modemde zaten kayıtlı olanlar "yeni" sayılmaz
                c = self.cihazlar[mac] = {"ilk": simdi, "tohum": self.ilk_kurulum}
                self.kirli = True
            for k, v in (("host_adi", host_adi), ("ip", ip), ("bant", bant)):
                if v and c.get(k) != v:
                    c[k] = v
                    self.kirli = True
            if aktif:
                if simdi - c.get("son", 0) > 60:
                    self.kirli = True
                c["son"] = simdi
            return yeni and not self.ilk_kurulum

    def adlandir(self, mac, ad):
        with self.kilit:
            c = self.cihazlar.setdefault(mac, {"ilk": int(time.time())})
            if ad:
                c["ad"] = ad[:40]
            else:
                c.pop("ad", None)
            self.kirli = True
        self.kaydet()

    def meta(self, mac, alanlar: dict):
        """Cihaza ait elle girilen bilgiler: cins, grup, not, guvenilir."""
        with self.kilit:
            c = self.cihazlar.setdefault(mac, {"ilk": int(time.time())})
            for k, v in alanlar.items():
                if v in ("", None, False):
                    c.pop(k, None)
                else:
                    c[k] = v
            self.kirli = True
        self.kaydet()

    def ayarla(self, anahtar, deger):
        with self.kilit:
            self.ayar[anahtar] = deger
            self.kirli = True
        self.kaydet()

    def kaydet(self):
        with self.kilit:
            if not self.kirli:
                return
            KLASOR.mkdir(parents=True, exist_ok=True)
            gecici = DOSYA.with_suffix(".tmp")
            gecici.write_text(json.dumps(self.veri, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(gecici, DOSYA)
            self.kirli = False
            self.ilk_kurulum = False

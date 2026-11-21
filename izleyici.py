"""İnternet kesintisi izleyicisi ve hız testi (modemden bağımsız, bu bilgisayardan ölçer)."""
import logging
import os
import socket
import statistics
import threading
import time

import requests

log = logging.getLogger("panel")
HEDEFLER = [("1.1.1.1", 443), ("8.8.8.8", 53), ("9.9.9.9", 443)]
ARALIK = 15          # sn
ESIK = 2             # art arda bu kadar başarısız deneme = kesinti
HIZ_ADRES = "https://speed.cloudflare.com"


def ulasir(adres, port, sure=2.5) -> bool:
    try:
        socket.create_connection((adres, port), timeout=sure).close()
        return True
    except OSError:
        return False


class KesintiIzleyici:
    """Her 15 sn'de birkaç bilinen sunucuya bağlanmayı dener; hiçbiri cevap vermezse kesinti başlar."""

    def __init__(self, gecmis, bildir, modem_host="192.168.1.1"):
        self.gecmis = gecmis
        self.modem_host = modem_host
        self.bildir = bildir      # bildir(baslik, metin)
        self.basarisiz = 0
        self.acik = None          # (kayıt kimliği, başlangıç, tür)
        self.durum = "bilinmiyor"
        self.calisiyor = True

    def calis(self):
        while self.calisiyor:
            try:
                self._dene()
            except Exception:
                log.exception("kesinti izleyici")
            time.sleep(ARALIK)

    def _dene(self):
        if any(ulasir(a, p) for a, p in HEDEFLER):
            self.basarisiz = 0
            self.durum = "var"
            if self.acik:
                kimlik, bas, tur = self.acik
                bitis = time.time()
                self.gecmis.kesinti_bitir(kimlik, bitis)
                self.acik = None
                dk = max(1, round((bitis - bas) / 60))
                self.bildir("İnternet geri geldi", f"{'İnternet' if tur == 'internet' else 'Ağ bağlantısı'} {dk} dakika kesikti.")
            return
        self.basarisiz += 1
        if self.basarisiz >= ESIK and not self.acik:
            # modem cevap veriyorsa sorun internet hattında, vermiyorsa bu bilgisayarın ağ bağlantısında
            tur = "internet" if ulasir(self.modem_host, 80) else "ag"
            bas = time.time() - ARALIK * (ESIK - 1)
            self.acik = (self.gecmis.kesinti_baslat(tur, bas), bas, tur)
            self.durum = "yok"
            log.info("kesinti başladı: %s", tur)


def hiz_testi(ilerleme=None) -> dict:
    """Cloudflare'in hız testi sunucusuyla gecikme, indirme ve yükleme ölçer (~15 sn)."""
    o = requests.Session()
    o.headers["User-Agent"] = "WaveSnap"
    ilerle = ilerleme or (lambda *_: None)

    ilerle("gecikme", 0)
    sureler = []
    for _ in range(6):
        t = time.perf_counter()
        o.get(f"{HIZ_ADRES}/__down?bytes=0", timeout=5)
        sureler.append((time.perf_counter() - t) * 1000)
    gecikme = round(statistics.median(sureler[1:]), 1)

    def indir(bayt):
        t = time.perf_counter()
        toplam = 0
        with o.get(f"{HIZ_ADRES}/__down?bytes={bayt}", stream=True, timeout=30) as r:
            for parca in r.iter_content(65536):
                toplam += len(parca)
                ilerle("indirme", toplam * 8 / max(time.perf_counter() - t, 1e-3) / 1e6)
        return toplam * 8 / (time.perf_counter() - t) / 1e6

    indir(2_000_000)  # ısınma
    indirme = max(indir(25_000_000), indir(25_000_000))

    veri = os.urandom(8_000_000)
    yukler = []
    for _ in range(2):
        ilerle("yukleme", yukler[-1] if yukler else 0)
        t = time.perf_counter()
        o.post(f"{HIZ_ADRES}/__up", data=veri, timeout=60)
        yukler.append(len(veri) * 8 / (time.perf_counter() - t) / 1e6)
    yukleme = max(yukler)
    return {"indirme": round(indirme, 1), "yukleme": round(yukleme, 1), "gecikme": gecikme}


class HizTesti:
    """Arka planda tek seferde bir test çalıştırır; arayüz ilerlemeyi sorarak izler."""

    def __init__(self, gecmis):
        self.gecmis = gecmis
        self.durum = {"calisiyor": False}
        self.kilit = threading.Lock()

    def baslat(self) -> bool:
        with self.kilit:
            if self.durum.get("calisiyor"):
                return False
            self.durum = {"calisiyor": True, "asama": "gecikme", "anlik": 0}
        threading.Thread(target=self._calis, daemon=True).start()
        return True

    def _calis(self):
        try:
            sonuc = hiz_testi(lambda asama, anlik: self.durum.update(asama=asama, anlik=round(anlik, 1)))
            self.gecmis.hiz_testi(sonuc["indirme"], sonuc["yukleme"], sonuc["gecikme"])
            self.durum = {"calisiyor": False, "sonuc": sonuc, "zaman": time.time()}
        except requests.RequestException as e:
            self.durum = {"calisiyor": False, "hata": f"Hız testi sunucusuna ulaşılamadı ({e.__class__.__name__})."}
        except Exception as e:
            log.exception("hız testi")
            self.durum = {"calisiyor": False, "hata": f"Hız testi tamamlanamadı: {e}"}

"""Modem Paneli yerel sunucusu — yalnız bu bilgisayardan (127.0.0.1) erişilir."""
import json
import logging
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import depo
import dil
import sifre_kasasi
import surucu
from servis import ModemMesgul, Panel, Reddedildi
from surucu import GirisHatasi

KLASOR = Path(__file__).resolve().parent
WEB = KLASOR / "web"
PORT = 8765
IZINLI_HOST = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
TURLER = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
          ".woff2": "font/woff2", ".png": "image/png", ".ico": "image/x-icon"}

panel = Panel()
sunucu = None


class Isleyici(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, kod, veri):
        govde = json.dumps(veri, ensure_ascii=False).encode("utf-8")
        self.send_response(kod)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(govde)))
        self.end_headers()
        self.wfile.write(govde)

    def _dosya(self, yol: Path):
        yol = yol.resolve()
        if not yol.is_file() or WEB not in yol.parents:
            self.send_error(404)
            return
        govde = yol.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TURLER.get(yol.suffix, "application/octet-stream"))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(govde)))
        self.end_headers()
        self.wfile.write(govde)

    def _modem(self, is_):
        """Modeme dokunan bir işi sırayla çalıştırır ve sonucu JSON döndürür."""
        if panel.duraklat_bitis and panel.duraklat_bitis > __import__("time").time():
            return self._json(409, {"hata": "WaveSnap modemi bırakmış durumda; önce Ayarlar'dan devam ettirin."})
        try:
            with panel.kilit:
                sonuc = is_()
                panel.ek_zaman = 0  # bir sonraki okumada listeleri tazele
        except ModemMesgul:
            return self._json(409, {"hata": "Modemin kendi sayfasında açık bir oturum var; o kapanınca tekrar deneyin."})
        except (Reddedildi, ValueError) as h:
            return self._json(409, {"hata": str(h)})
        except Exception as h:
            logging.getLogger("panel").exception("modem işlemi")
            return self._json(502, {"hata": f"Modem işlemi tamamlanamadı ({h})."})
        return self._json(200, sonuc if isinstance(sonuc, dict) else {"sonuc": sonuc})

    def _guvenli(self) -> bool:
        # başka bir web sitesinin tarayıcı üzerinden bu panele komut göndermesini engeller
        if self.headers.get("Host") not in IZINLI_HOST:
            return False
        if self.command == "POST" and self.headers.get("X-Panel") != "1":
            return False
        return True

    def _govde(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _csv(self, tur, gun):
        """Excel'in Türkçe karakterleri doğru açması için UTF-8 BOM ve noktalı virgül."""
        import csv
        import io
        cikti = io.StringIO()
        w = csv.writer(cikti, delimiter=";")
        yaz = w.writerow
        w = type("Ceviren", (), {"writerow": staticmethod(lambda satir: yaz([dil.t(str(x)) if isinstance(x, str) else x for x in satir]))})
        adlar = {c["mac"]: c for c in panel.cihazlar}
        ad = lambda m: (adlar.get(m, {}).get("ad") or adlar.get(m, {}).get("host_adi") or "")
        if tur == "kullanim":
            w.writerow(["Tarih", "Cihaz", "MAC", "İndirme (MB)", "Yükleme (MB)"])
            for mac, g, i, y in panel.gecmis.kullanim_tablosu(max(1, min(400, gun))):
                w.writerow([g, ad(mac), mac, f"{(i or 0) / 1e6:.1f}".replace(".", ","), f"{(y or 0) / 1e6:.1f}".replace(".", ",")])
            dosya = "wavesnap-kullanim.csv"
        else:
            w.writerow(["Ad", "Modemdeki ad", "Üretici", "Tür", "Grup", "IP", "MAC", "Bağlantı", "Durum", "Sabit IP",
                        "Hız sınırı (Mbps)", "Engelli", "Güvenilir", "Not"])
            for c in panel.cihazlar:
                w.writerow([c["ad"], c["host_adi"], c["uretici"], c["cins"], c["grup"], c["ip"], c["mac"],
                            "Kablo" if c["tur"] == "kablo" else (f"{c['bant']} GHz" if c["bant"] else "Wi-Fi"),
                            "Bağlı" if c["aktif"] else "Çevrim dışı", c["sabit_ip"] or "", c["sinir"] or "",
                            "Evet" if c["engelli"] else "", "Evet" if c["guvenilir"] else "", c["not"]])
            dosya = "wavesnap-cihazlar.csv"
        govde = ("﻿" + cikti.getvalue()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{dosya}"')
        self.send_header("Content-Length", str(len(govde)))
        self.end_headers()
        self.wfile.write(govde)

    def do_GET(self):
        if not self._guvenli():
            return self.send_error(403)
        from urllib.parse import parse_qs, urlsplit
        yol = urlsplit(self.path).path
        sorgu = parse_qs(urlsplit(self.path).query)
        if yol == "/api/durum":
            panel.kalp()
            return self._json(200, panel.ozet())
        if yol == "/api/gecmis":
            gun = max(1, min(400, int(sorgu.get("gun", ["7"])[0])))
            g = panel.gecmis
            return self._json(200, {**g.ozet(gun), "olaylar": g.olaylar(300), "kesintiler": g.kesintiler(100),
                                    "hiz_testleri": g.hiz_testleri(20), "trafik": g.trafik_gecmisi(24)})
        if yol == "/api/cihaz-gecmisi":
            mac = sorgu.get("mac", [""])[0].upper()
            return self._json(200, {"gunluk": panel.gecmis.cihaz_gunluk(mac, 30), "olaylar": panel.gecmis.olaylar(50, mac)})
        if yol == "/api/hiz-testi":
            return self._json(200, panel.hiz.durum)
        if yol == "/api/kesif":
            from surucu import kesif
            sonuc = kesif.tani(sorgu.get("adres", [""])[0].strip())
            sonuc["mevcut"] = panel.depo.ayar.get("surucu") or (panel.surucu.KIMLIK if panel.kurulum_var() else "")
            return self._json(200, sonuc)
        if yol == "/api/diller":
            return self._json(200, dil.diller())
        if yol == "/api/modem-ayar":
            return self._modem(lambda: {**panel._oturum().ayar_oku(), "takvimler": panel.depo.ayar.get("takvimler") or {}})
        if yol == "/api/kayitlar":
            return self._modem(lambda: {"satirlar": panel._oturum().kayitlar()})
        if yol == "/api/qr":
            ag = sorgu.get("ag", ["ana"])[0]
            return self._modem(lambda: panel._oturum().ana_ag() if ag == "ana" else
                               {k: (panel._oturum().ek_ag_oku() or {}).get(k, "") for k in ("ssid", "sifre")})
        if yol == "/api/disa-aktar":
            return self._csv(sorgu.get("tur", ["cihazlar"])[0], int(sorgu.get("gun", ["30"])[0]))
        if yol == "/":
            yol = "/index.html"
        self._dosya(WEB / yol.lstrip("/"))

    def do_POST(self):
        if not self._guvenli():
            return self.send_error(403)
        yol = self.path.split("?")[0]
        try:
            veri = self._govde()
        except ValueError:
            return self._json(400, {"hata": "Geçersiz istek."})

        if yol == "/api/kurulum":
            import ipaddress
            kimlik = veri.get("surucu") or panel.surucu.KIMLIK
            host = str(veri.get("adres") or panel.surucu.host).strip()
            try:
                if not ipaddress.ip_address(host).is_private:
                    raise ValueError
            except ValueError:
                return self._json(400, {"hata": "Modem adresi yerel bir IP adresi olmalı (ör. 192.168.1.1)."})
            if kimlik not in surucu.SURUCULER:
                return self._json(400, {"hata": "Bilinmeyen modem türü."})
            if not surucu.SURUCULER[kimlik].GIRIS_GEREKIR:
                panel.surucu_degistir(kimlik, host)
                panel.kurulum_tamam()
                return self._json(200, {"tamam": True})
            kullanici = (veri.get("kullanici") or "admin").strip()
            sifre = veri.get("sifre") or ""
            with panel.kilit:
                panel._oturumu_kapat()  # modem tek oturum kabul ediyor
                m = surucu.olustur(kimlik, host)
                try:
                    m.giris(kullanici, sifre)
                except GirisHatasi as h:
                    return self._json(400, {"hata": str(h)})
                except Exception as h:
                    return self._json(502, {"hata": f"Modeme ulaşılamadı: {h.__class__.__name__}"})
                finally:
                    m.cikis()
                sifre_kasasi.kaydet(kullanici, sifre)
                if (kimlik, host) != (panel.surucu.KIMLIK, panel.surucu.host) or not panel.depo.ayar.get("surucu"):
                    panel.surucu_degistir(kimlik, host)
            panel.kurulum_tamam()
            return self._json(200, {"tamam": True})

        if yol == "/api/islem":
            try:
                mesaj = panel.islem(veri.get("islem", ""), veri.get("mac", ""), veri)
            except Reddedildi as h:
                return self._json(409, {"hata": str(h)})
            except Exception as h:
                logging.getLogger("panel").exception("işlem hatası")
                return self._json(502, {"hata": f"Modem işlemi tamamlayamadı ({h}). Durumu yeniden okuyup kontrol edin."})
            return self._json(200, {**panel.ozet(), "sonuc": mesaj})

        if yol == "/api/duraklat":
            panel.duraklat(int(veri.get("dakika") or 10))
            return self._json(200, panel.ozet())
        if yol == "/api/devam":
            panel.devam(zorla=bool(veri.get("zorla")))
            return self._json(200, panel.ozet())
        if yol == "/api/ayar":
            if "bildirim" in veri:
                panel.depo.ayarla("bildirim", bool(veri["bildirim"]))
            if "dil" in veri and dil.var_mi(veri["dil"]):
                panel.depo.ayarla("dil", veri["dil"])
                dil.ayarla(veri["dil"])
            if veri.get("tema") in ("storm", "desert", "electric"):
                panel.depo.ayarla("tema", veri["tema"])
            if isinstance(veri.get("sira"), list):
                panel.depo.ayarla("sira", [str(m).upper()[:17] for m in veri["sira"]][:500])
            return self._json(200, panel.ozet())
        if yol == "/api/takvim":
            mac = str(veri.get("mac", "")).upper()
            if not mac:
                return self._json(400, {"hata": "Cihaz seçilmedi."})
            return self._modem(lambda: panel.takvim_kaydet(mac, veri.get("takvim")))
        if yol == "/api/modem-ayar":
            tur = veri.get("tur")
            takvim = veri.get("takvim") or [[False] * 48 for _ in range(7)]
            if tur == "wifi_zaman":
                return self._modem(lambda: panel._oturum().wifi_zaman(bool(veri.get("acik")), takvim))
            if tur == "led":
                return self._modem(lambda: panel._oturum().led(bool(veri.get("acik")), str(veri.get("baslangic", "22:00"))[:5],
                                                       str(veri.get("bitis", "07:00"))[:5]))
            if tur == "ek_ag":
                ssid, sifre = str(veri.get("ssid", "")).strip(), str(veri.get("sifre", ""))
                if veri.get("acik") and not (1 <= len(ssid) <= 32 and 8 <= len(sifre) <= 63):
                    return self._json(409, {"hata": "Ağ adı 1-32, şifre 8-63 karakter olmalı."})
                return self._modem(lambda: panel._oturum().ek_ag(bool(veri.get("acik")), ssid, sifre, bool(veri.get("ayirma", True))))
            return self._json(400, {"hata": "Bilinmeyen ayar."})
        if yol == "/api/baglanti-testi":
            return self._json(200, baglanti_testi())
        if yol == "/api/yeniden-baslat":
            return self._modem(lambda: panel._oturum().yeniden_baslat())
        if yol == "/api/hiz-testi":
            panel.hiz.baslat()
            return self._json(200, panel.hiz.durum)
        if yol == "/api/bildirim-dene":
            import bildirim
            bildirim.gonder("WaveSnap", dil.t("Bildirimler çalışıyor. Yeni bir cihaz bağlanınca böyle haber vereceğim."))
            return self._json(200, {"tamam": True})
        if yol == "/api/kapat":
            panel.durdur()  # önce modemden çık, sonra cevap ver
            self._json(200, {"tamam": True})
            threading.Thread(target=sunucu.shutdown, daemon=True).start()
            return
        self.send_error(404)


def baglanti_testi() -> dict:
    """Sorunun nerede olduğunu adım adım bulur: bilgisayar → modem → hat → internet → DNS."""
    import socket
    from izleyici import HEDEFLER, ulasir
    from servis import bu_pc_ip
    adimlar, ozet = [], None
    ip = bu_pc_ip(panel.surucu.host)
    adimlar.append((bool(ip), f"Bu bilgisayar ağa bağlı ({ip})" if ip else "Bu bilgisayar ağa bağlı değil"))
    modem = ulasir(panel.surucu.host, 80)
    adimlar.append((modem, "Modeme ulaşılıyor" if modem else "Modeme ulaşılamıyor"))
    hat = panel.hat or {}
    hat_ok = hat.get("baglanti") == "Connected" and hat.get("hat_durumu", "Up") == "Up"
    if modem:
        adimlar.append((hat_ok, "Modemin internet hattı bağlı" if hat_ok else "Modemin internet hattı bağlı görünmüyor"))
    net = any(ulasir(a, p) for a, p in HEDEFLER)
    adimlar.append((net, "İnternete çıkılabiliyor" if net else "İnternete çıkılamıyor"))
    try:
        socket.getaddrinfo("www.google.com", 443)
        dns = True
    except OSError:
        dns = False
    adimlar.append((dns, "Site adları çözülebiliyor (DNS)" if dns else "Site adları çözülemiyor (DNS)"))
    if not ip:
        ozet = "Sorun bu bilgisayarın ağ bağlantısında: kabloyu ya da Wi-Fi'yi kontrol edin."
    elif not modem:
        ozet = "Bilgisayar modeme ulaşamıyor: modem kapalı olabilir ya da kablo/Wi-Fi bağlantısı kopmuş."
    elif not net and not hat_ok:
        ozet = "Sorun internet hattında (internet sağlayıcısı tarafı). Modemi yeniden başlatmayı deneyin; düzelmezse internet sağlayıcınızı arayın."
    elif not net:
        ozet = "Modem bağlı görünüyor ama internete çıkılamıyor. Modemi yeniden başlatmayı deneyin."
    elif not dns:
        ozet = "İnternet var ama site adları çözülemiyor (DNS sorunu)."
    else:
        ozet = "Her şey yolunda: internet çalışıyor. Yavaşlık varsa sorun Wi-Fi sinyalinde ya da yoğun kullanan bir cihazda olabilir."
    return {"adimlar": adimlar, "ozet": ozet}


def calistir():
    global sunucu
    depo.KLASOR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=depo.KLASOR / "panel.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    sunucu = ThreadingHTTPServer(("127.0.0.1", PORT), Isleyici)
    sunucu.daemon_threads = True
    threading.Thread(target=panel.calis, daemon=True).start()
    logging.getLogger("panel").info("panel başladı")
    try:
        sunucu.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        panel.durdur()
        sys.exit(0)


if __name__ == "__main__":
    calistir()

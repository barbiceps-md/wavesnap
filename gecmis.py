"""Geçmiş kayıtları (SQLite): cihaz başına saatlik kullanım, geldi/gitti olayları, kesintiler, hız testleri, dakikalık trafik.

Dosya: <veri klasörü>/gecmis.db — yalnız bu bilgisayarda kalır.
"""
import sqlite3
import threading
import time

import depo

DOSYA = depo.KLASOR / "gecmis.db"
SAKLAMA_GUN = 400  # bu kadar günden eski kayıtlar silinir

SEMA = """
CREATE TABLE IF NOT EXISTS kullanim (mac TEXT, saat INTEGER, indirme INTEGER, yukleme INTEGER, PRIMARY KEY (mac, saat));
CREATE TABLE IF NOT EXISTS olay (zaman INTEGER, mac TEXT, tur TEXT, ayrinti TEXT);
CREATE INDEX IF NOT EXISTS olay_zaman ON olay (zaman);
CREATE TABLE IF NOT EXISTS kesinti (id INTEGER PRIMARY KEY, baslangic INTEGER, bitis INTEGER, tur TEXT);
CREATE TABLE IF NOT EXISTS hiz_testi (zaman INTEGER, indirme REAL, yukleme REAL, gecikme REAL);
CREATE TABLE IF NOT EXISTS trafik_dk (zaman INTEGER PRIMARY KEY, indirme INTEGER, yukleme INTEGER);
"""


class Gecmis:
    def __init__(self):
        depo.KLASOR.mkdir(parents=True, exist_ok=True)
        self.kilit = threading.Lock()
        self.db = sqlite3.connect(DOSYA, check_same_thread=False)
        self.db.executescript(SEMA)
        self.dk = None          # birikmekte olan dakika: [dakika, toplam indirme, toplam yükleme, örnek sayısı]
        self.temizle()

    def _yaz(self, sql, args=()):
        with self.kilit:
            self.db.execute(sql, args)
            self.db.commit()

    def _oku(self, sql, args=()):
        with self.kilit:
            return self.db.execute(sql, args).fetchall()

    def temizle(self):
        sinir = int(time.time()) - SAKLAMA_GUN * 86400
        with self.kilit:
            for tablo, alan in (("kullanim", "saat"), ("olay", "zaman"), ("kesinti", "baslangic"), ("hiz_testi", "zaman")):
                self.db.execute(f"DELETE FROM {tablo} WHERE {alan} < ?", (sinir,))
            self.db.execute("DELETE FROM trafik_dk WHERE zaman < ?", (int(time.time()) - 8 * 86400,))
            self.db.commit()

    # ---------- yazma ----------
    def kullanim(self, mac, indirme, yukleme, zaman=None):
        if indirme <= 0 and yukleme <= 0:
            return
        saat = int((zaman or time.time()) // 3600 * 3600)
        self._yaz("""INSERT INTO kullanim VALUES (?, ?, ?, ?)
                     ON CONFLICT (mac, saat) DO UPDATE SET indirme = indirme + excluded.indirme, yukleme = yukleme + excluded.yukleme""",
                  (mac, saat, int(indirme), int(yukleme)))

    def olay(self, mac, tur, ayrinti=""):
        self._yaz("INSERT INTO olay VALUES (?, ?, ?, ?)", (int(time.time()), mac, tur, ayrinti))

    def trafik(self, zaman, indirme, yukleme):
        dakika = int(zaman // 60 * 60)
        if self.dk and self.dk[0] != dakika:
            d = self.dk
            self._yaz("INSERT OR REPLACE INTO trafik_dk VALUES (?, ?, ?)", (d[0], d[1] // d[3], d[2] // d[3]))
            self.dk = None
        if not self.dk:
            self.dk = [dakika, 0, 0, 0]
        self.dk[1] += int(indirme); self.dk[2] += int(yukleme); self.dk[3] += 1

    def kesinti_baslat(self, tur, zaman=None) -> int:
        with self.kilit:
            c = self.db.execute("INSERT INTO kesinti (baslangic, bitis, tur) VALUES (?, NULL, ?)", (int(zaman or time.time()), tur))
            self.db.commit()
            return c.lastrowid

    def kesinti_bitir(self, kimlik, zaman=None):
        self._yaz("UPDATE kesinti SET bitis = ? WHERE id = ?", (int(zaman or time.time()), kimlik))

    def hiz_testi(self, indirme, yukleme, gecikme):
        self._yaz("INSERT INTO hiz_testi VALUES (?, ?, ?, ?)", (int(time.time()), indirme, yukleme, gecikme))

    # ---------- okuma ----------
    def ozet(self, gun: int) -> dict:
        simdi = int(time.time())
        bas = simdi - gun * 86400
        cihaz = self._oku("""SELECT mac, SUM(indirme), SUM(yukleme) FROM kullanim WHERE saat >= ?
                              GROUP BY mac ORDER BY SUM(indirme) + SUM(yukleme) DESC""", (bas,))
        if gun <= 1:  # son 24 saat: saatlik
            dilim = self._oku("SELECT saat, SUM(indirme), SUM(yukleme) FROM kullanim WHERE saat >= ? GROUP BY saat ORDER BY saat", (bas,))
        else:         # günlük (yerel saatle)
            dilim = self._oku("""SELECT CAST(strftime('%s', date(saat, 'unixepoch', 'localtime')) AS INTEGER) AS g, SUM(indirme), SUM(yukleme)
                                 FROM kullanim WHERE saat >= ? GROUP BY g ORDER BY g""", (bas,))
        return {
            "cihaz": [{"mac": m, "indirme": i or 0, "yukleme": y or 0} for m, i, y in cihaz],
            "dilim": [{"zaman": z, "indirme": i or 0, "yukleme": y or 0} for z, i, y in dilim],
            "dilim_tur": "saat" if gun <= 1 else "gun",
        }

    def cihaz_gunluk(self, mac, gun=30):
        bas = int(time.time()) - gun * 86400
        return [{"zaman": z, "indirme": i, "yukleme": y} for z, i, y in self._oku(
            """SELECT CAST(strftime('%s', date(saat, 'unixepoch', 'localtime')) AS INTEGER) AS g, SUM(indirme), SUM(yukleme)
               FROM kullanim WHERE mac = ? AND saat >= ? GROUP BY g ORDER BY g""", (mac, bas))]

    def olaylar(self, limit=200, mac=None):
        if mac:
            r = self._oku("SELECT zaman, mac, tur, ayrinti FROM olay WHERE mac = ? ORDER BY zaman DESC LIMIT ?", (mac, limit))
        else:
            r = self._oku("SELECT zaman, mac, tur, ayrinti FROM olay ORDER BY zaman DESC LIMIT ?", (limit,))
        return [{"zaman": z, "mac": m, "tur": t, "ayrinti": a} for z, m, t, a in r]

    def kesintiler(self, limit=100):
        return [{"baslangic": b, "bitis": e, "tur": t} for b, e, t in self._oku(
            "SELECT baslangic, bitis, tur FROM kesinti ORDER BY baslangic DESC LIMIT ?", (limit,))]

    def hiz_testleri(self, limit=20):
        return [{"zaman": z, "indirme": i, "yukleme": y, "gecikme": g} for z, i, y, g in self._oku(
            "SELECT zaman, indirme, yukleme, gecikme FROM hiz_testi ORDER BY zaman DESC LIMIT ?", (limit,))]

    def trafik_gecmisi(self, saat=24):
        bas = int(time.time()) - saat * 3600
        return [[z, i, y] for z, i, y in self._oku("SELECT zaman, indirme, yukleme FROM trafik_dk WHERE zaman >= ? ORDER BY zaman", (bas,))]

    def kullanim_tablosu(self, gun=30):
        bas = int(time.time()) - gun * 86400
        return self._oku("""SELECT mac, date(saat, 'unixepoch', 'localtime') AS g, SUM(indirme), SUM(yukleme)
                            FROM kullanim WHERE saat >= ? GROUP BY mac, g ORDER BY g, mac""", (bas,))

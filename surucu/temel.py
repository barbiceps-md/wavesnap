"""Modem sürücüsü sözleşmesi.

WaveSnap'in geri kalanı modemle yalnız bu arayüzden konuşur. Yeni bir marka/model eklemek = bu sınıftan türeyen bir
sürücü yazıp `surucu/__init__.py` içindeki listeye eklemek. Sürücü yalnız modemin anladığı dili bilir; oturum
politikası (tek oturum, pencere kapalıyken bırakma), geçmiş, bildirim, takvim ve girdi denetimi panelde kalır.

Bir sürücü desteklemediği özelliği `yetenekler` kümesine koymaz; arayüz o düğmeleri göstermez, panel o işlemi
reddeder. Varsayılan gövdeler "desteklenmiyor" hatası verir.

Döndürülen cihaz satırı (oku_cihazlar):
    mac         "AA:BB:CC:DD:EE:FF" (büyük harf)
    host_adi    cihazın kendini tanıttığı ad ("" olabilir)
    ip          "192.168.1.23" ("" olabilir)
    aktif       şu an bağlı mı
    kablo       kablolu mu
    bant        "2.4" / "5" / "6" / None (kablolu ya da bilinmiyor)
    indirilen   modemin bu cihaz için tuttuğu toplam indirme sayacı (bayt; yoksa 0)
    yuklenen    toplam yükleme sayacı (bayt; yoksa 0)
    baglanti    Wi-Fi bağlantı hızı (Mbps; yoksa 0)
"""


class ModemHatasi(Exception):
    """Modem isteği reddetti ya da beklenmeyen cevap verdi."""


class OturumHatasi(ModemHatasi):
    """Modemdeki oturum düştü; sürücü bir kez yeniden girmeyi dener."""


class GirisHatasi(Exception):
    """Kullanıcı adı/şifre kabul edilmedi. Panel tekrar denemez (modemler birkaç hatada kilitlenir)."""


class Reddedildi(Exception):
    """Kullanıcıya gösterilecek, işlemin neden yapılmadığını anlatan hata."""


class Yetenek:
    CIHAZLAR = "cihazlar"          # cihaz listesi (bağlı + modemin hatırladıkları)
    SAYAC = "sayac"                # cihaz başına trafik sayacı (anlık hız ve kullanım geçmişi bundan çıkar)
    ENGELLE = "engelle"            # Wi-Fi'den engelleme
    DURDUR = "durdur"              # interneti durdurma (cihaz ağda kalır)
    SINIR = "sinir"                # cihaz başına hız sınırı
    SABIT_IP = "sabit_ip"          # DHCP adres ayırma
    HAT = "hat"                    # internet hattı bilgisi (senkron hızı, SNR, açık kalma süresi)
    WIFI_ZAMAN = "wifi_zaman"      # Wi-Fi'yi saatle kapatma
    LED = "led"                    # ışıkları saatle kapatma
    MISAFIR = "misafir"            # misafir / ek Wi-Fi ağı
    WIFI_QR = "wifi_qr"            # ana ağın adı ve şifresi okunabiliyor (QR kodu için)
    YENIDEN_BASLAT = "yeniden_baslat"
    KAYITLAR = "kayitlar"          # modemin kendi olay kayıtları


class Surucu:
    KIMLIK = ""                    # ayarlarda saklanan kısa ad, ör. "tplink_cgi"
    AD = ""                        # kullanıcıya görünen ad, ör. "TP-Link (VC220 türü arayüz)"
    VARSAYILAN_KULLANICI = "admin"
    GIRIS_GEREKIR = True           # modem şifresi ister mi
    TEK_OTURUM = True              # modem aynı anda tek yönetici oturumu kabul ediyor mu ("modemi bırak" düğmesi)
    yetenekler: frozenset = frozenset()
    DURDURMA_YUVASI = 0            # aynı anda internetini durdurabildiği en fazla cihaz (0 = sınırsız/yok)
    SINIR_YUVASI = 0               # hız sınırı konabilen en fazla cihaz

    def __init__(self, host: str = "192.168.1.1"):
        self.host = host

    # ---------- oturum ----------
    @property
    def oturum_acik(self) -> bool:
        return False

    def baskasi_girisli(self) -> bool:
        """Modemin kendi web sayfasında açık bir oturum var mı? (tek oturumlu modemlerde panel onu düşürmez)"""
        return False

    def giris(self, kullanici: str, sifre: str) -> None:
        raise NotImplementedError

    def cikis(self) -> None:
        pass

    def unut(self) -> None:
        """Oturumu modeme haber vermeden unut (bağlantı koptuğunda; çıkış isteği zaten gidemez)."""

    # ---------- okuma ----------
    def oku_ek(self) -> dict:
        """Yavaş değişen listeler: {"engelli": set(mac), "sinirlar": {mac: mbps}, "sabitler": {mac: ip},
        "durdurulan": [mac] ya da None (okunamadı), "filtre_acik": bool}"""
        return {"engelli": set(), "sinirlar": {}, "sabitler": {}, "durdurulan": None, "filtre_acik": False}

    def oku_cihazlar(self) -> list:
        raise NotImplementedError

    def oku_hat(self) -> dict:
        """{"baglanti", "internet_sure" (sn ya da None), "modem_sure", "tur", "hat_durumu", "indirme_kbps",
        "yukleme_kbps", "snr_indirme", "snr_yukleme", "model", "yazilim"}"""
        return {}

    @classmethod
    def tani(cls, host: str) -> bool:
        """Şifre kullanmadan: bu adresteki modem bu sürücünün dilini konuşuyor mu?"""
        return False

    def lan_onek(self) -> str:
        """Sabit IP'nin hangi ağda olması gerektiği, ör. "192.168.1." """
        return self.host.rsplit(".", 1)[0] + "."

    # ---------- işlemler (her biri kullanıcıya gösterilecek kısa bir sonuç cümlesi döndürür) ----------
    def _yok(self):
        raise Reddedildi("Bu modem bu özelliği desteklemiyor.")

    def engelle(self, mac: str) -> str: self._yok()
    def engel_kaldir(self, mac: str) -> str: self._yok()
    def sinir(self, mac: str, mbps: float) -> str: self._yok()
    def sinir_kaldir(self, mac: str) -> str: self._yok()
    def sabit(self, mac: str, ip: str) -> str: self._yok()
    def sabit_kaldir(self, mac: str) -> str: self._yok()

    def durdurulanlari_yaz(self, macler: list, koru_mac: str) -> None:
        """Interneti durdurulmuş cihaz listesini modeme yazar (boş liste = herkes serbest)."""
        self._yok()

    # ---------- modem ayarları ----------
    def ayar_oku(self) -> dict:
        """{"wifi": [{"yol", "bant", "ssid", "zaman_acik", "takvim"}], "led": {...} | None, "ek_ag": {...} | None}"""
        return {"wifi": [], "led": None, "ek_ag": None}

    def wifi_zaman(self, acik: bool, takvim: list) -> str: self._yok()
    def led(self, acik: bool, baslangic: str, bitis: str) -> str: self._yok()
    def ek_ag(self, acik: bool, ssid: str, sifre: str, ayirma: bool) -> str: self._yok()
    def ana_ag(self) -> dict: self._yok()
    def ek_ag_oku(self): return None
    def yeniden_baslat(self) -> str: self._yok()
    def kayitlar(self) -> list: self._yok()

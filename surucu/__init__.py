"""Modem sürücüleri. Yeni sürücü: temel.Surucu'dan türet, buraya ekle."""
from .fritzbox import FritzBox
from .genel import Genel
from .mikrotik import MikroTik
from .openwrt import OpenWrt
from .temel import GirisHatasi, ModemHatasi, OturumHatasi, Reddedildi, Surucu, Yetenek
from .tplink_cgi import TplinkCgi

TAM = (TplinkCgi, FritzBox, OpenWrt, MikroTik)  # modem şifresiyle tam kontrol veren sürücüler (tanıma sırası)
SURUCULER = {s.KIMLIK: s for s in (*TAM, Genel)}
VARSAYILAN = TplinkCgi.KIMLIK      # eski kurulumlar (sürücü seçimi yokken kurulmuş olanlar)


def olustur(kimlik: str = VARSAYILAN, host: str = "192.168.1.1") -> Surucu:
    return SURUCULER.get(kimlik or VARSAYILAN, SURUCULER[VARSAYILAN])(host)

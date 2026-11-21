"""Masaüstüne ve Başlat menüsüne 'WaveSnap' kısayolu kurar.

Başlat menüsü kısayolu, Windows bildirimlerinde 'Windows PowerShell' yerine 'WaveSnap' adı
ve simgesi görünsün diye uygulama kimliği (AppUserModelID) taşır.
"""
import sys
from pathlib import Path

import pythoncom
from win32com.client import Dispatch
from win32com.propsys import propsys, pscon
from win32com.shell import shell

from bildirim import BASLAT_KISAYOLU, UYGULAMA_KIMLIGI

KLASOR = Path(__file__).resolve().parent
PYTHONW = Path(sys.executable).with_name("pythonw.exe")
SIMGE = KLASOR / "web" / "simge.ico"


def kur(yol: Path, kimlik: bool):
    yol.parent.mkdir(parents=True, exist_ok=True)
    k = Dispatch("WScript.Shell").CreateShortcut(str(yol))
    k.TargetPath = str(PYTHONW)
    k.Arguments = f'"{KLASOR / "wavesnap.py"}"'
    k.WorkingDirectory = str(KLASOR)
    k.IconLocation = f"{SIMGE},0"
    k.Description = "WaveSnap — see and manage the devices on your network"
    k.Save()
    if kimlik:
        depo = propsys.SHGetPropertyStoreFromParsingName(str(yol), None, 2, propsys.IID_IPropertyStore)
        depo.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(UYGULAMA_KIMLIGI, pythoncom.VT_LPWSTR))
        depo.Commit()
    print("kuruldu:", yol)


def hepsini_kur():
    masaustu = Path(shell.SHGetFolderPath(0, 0x0010, None, 0))  # CSIDL_DESKTOPDIRECTORY
    # eski adlı kısayollar (Modem Paneli) yenisiyle değişir
    for eski in (masaustu / "Modem Paneli.lnk", BASLAT_KISAYOLU.with_name("Modem Paneli.lnk")):
        if eski.exists():
            eski.unlink()
            print("kaldırıldı:", eski)
    kur(masaustu / "WaveSnap.lnk", kimlik=False)
    kur(BASLAT_KISAYOLU, kimlik=True)


if __name__ == "__main__":
    hepsini_kur()

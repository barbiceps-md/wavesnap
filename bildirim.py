"""Masaüstü bildirimi — ek paket gerektirmez.

Windows: PowerShell'in WinRT köprüsüyle toast (Windows bildirimleri kapalıysa kendi kutumuz).
macOS: osascript. Linux: notify-send (yoksa kendi kutumuz).
"""
import base64
import os
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

import sistem

UYGULAMA_KIMLIGI = "WaveSnap.App"
BASLAT_KISAYOLU = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\WaveSnap.lnk"
# Başlat menüsü kısayolu yoksa Windows kendi kimliğimizle gelen bildirimi göstermez; o durumda PowerShell'in kimliği
POWERSHELL_KIMLIGI = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def windows_bildirimi_acik() -> bool:
    """Ayarlar > Sistem > Bildirimler'deki ana anahtar. Kapalıysa hiçbir toast görünmez."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\PushNotifications") as k:
            return winreg.QueryValueEx(k, "ToastEnabled")[0] != 0
    except OSError:
        return True


def kendi_kutumuz(baslik: str, metin: str) -> None:
    sistem.arkada_calistir(sistem.kendi_komutu("--popup", baslik, metin))


def gonder(baslik: str, metin: str) -> None:
    if sistem.MAC:
        def tirnak(s):
            return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
        sistem.arkada_calistir(["osascript", "-e", f"display notification {tirnak(metin)} with title {tirnak(baslik)}"])
    elif sistem.LINUX:
        if shutil.which("notify-send"):
            sistem.arkada_calistir(["notify-send", "--app-name=WaveSnap", baslik, metin])
        else:
            kendi_kutumuz(baslik, metin)
    elif not windows_bildirimi_acik():
        kendi_kutumuz(baslik, metin)
    else:
        _windows_toast(baslik, metin)


def _windows_toast(baslik: str, metin: str) -> None:
    kimlik = UYGULAMA_KIMLIGI if BASLAT_KISAYOLU.exists() else POWERSHELL_KIMLIGI
    xml = (
        '<toast activationType="protocol" launch="http://127.0.0.1:8765/">'
        "<visual><binding template=\"ToastGeneric\">"
        f"<text>{escape(baslik)}</text><text>{escape(metin)}</text>"
        "</binding></visual></toast>"
    )
    betik = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$x = New-Object Windows.Data.Xml.Dom.XmlDocument
$x.LoadXml(@'
{xml}
'@)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{kimlik}').Show([Windows.UI.Notifications.ToastNotification]::new($x))
"""
    kod = base64.b64encode(betik.encode("utf-16-le")).decode()
    sistem.arkada_calistir(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", kod])

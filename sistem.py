"""İşletim sistemine göre değişen her şey tek yerde: veri klasörü, pencere açma, kendini yeniden çalıştırma.

Windows, macOS ve Linux; kaynaktan (python wavesnap.py) ya da paketlenmiş uygulamadan (PyInstaller) çalışır.
"""
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

SURUM = "0.1.0"

WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"
LINUX = sys.platform.startswith("linux")
PAKETLI = getattr(sys, "frozen", False)

# web/, veri/ ve dil dosyalarının bulunduğu yer (paketlenmişse PyInstaller'ın açtığı klasör)
KAYNAK = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
GIZLI = 0x08000000 if WINDOWS else 0  # CREATE_NO_WINDOW: Windows'ta konsol penceresi açma


def _veri_klasoru() -> Path:
    if os.environ.get("WAVESNAP_VERI"):  # demo ve testler kendi klasörünü kullanır
        return Path(os.environ["WAVESNAP_VERI"])
    if WINDOWS:
        yerel = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        yeni, eski = yerel / "WaveSnap", yerel / "ModemPanel"
        if eski.exists() and not yeni.exists():  # ilk sürümlerin klasörü (Modem Paneli adı)
            try:
                eski.rename(yeni)
            except OSError:  # eski sürüm hâlâ açık: bu çalışmada eski yerden devam et
                return eski
        return yeni
    if MAC:
        return Path.home() / "Library" / "Application Support" / "WaveSnap"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "wavesnap"


VERI = _veri_klasoru()


def kendi_komutu(*arguman: str) -> list:
    """WaveSnap'i verilen argümanlarla yeniden başlatan komut (bildirim kutusu gibi ayrı işlemler için)."""
    if PAKETLI:
        return [sys.executable, *arguman]
    python = Path(sys.executable)
    if WINDOWS and python.with_name("pythonw.exe").exists():
        python = python.with_name("pythonw.exe")
    return [str(python), str(Path(__file__).resolve().parent / "wavesnap.py"), *arguman]


def arkada_calistir(komut: list) -> None:
    subprocess.Popen(komut, creationflags=GIZLI, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=not WINDOWS)


# ---------- pencere ----------
def _uygulama_tarayicisi():
    """'--app' penceresi açabilen (adres çubuğu olmayan) Chromium tabanlı bir tarayıcı."""
    if WINDOWS:
        yerler = []
        for kok in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if kok:
                yerler += [Path(kok) / r"Microsoft\Edge\Application\msedge.exe",
                           Path(kok) / r"Google\Chrome\Application\chrome.exe",
                           Path(kok) / r"BraveSoftware\Brave-Browser\Application\brave.exe"]
        return next((str(p) for p in yerler if p.exists()), None)
    if MAC:
        for ad in ("Google Chrome", "Microsoft Edge", "Chromium", "Brave Browser", "Vivaldi"):
            for kok in (Path("/Applications"), Path.home() / "Applications"):
                p = kok / f"{ad}.app" / "Contents" / "MacOS" / ad
                if p.exists():
                    return str(p)
        return None
    for ad in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
               "microsoft-edge-stable", "brave-browser", "vivaldi"):
        yol = shutil.which(ad)
        if yol:
            return yol
    return None


def _acik_pencereyi_one_getir() -> bool:
    """Windows'ta zaten açık bir WaveSnap penceresi varsa ikincisini açmak yerine onu öne getirir."""
    if not WINDOWS:
        return False
    try:
        import win32con
        import win32gui
    except ImportError:
        return False
    bulunan = []
    win32gui.EnumWindows(lambda h, _: bulunan.append(h) if win32gui.IsWindowVisible(h)
                         and win32gui.GetWindowText(h) == "WaveSnap" else None, None)
    if not bulunan:
        return False
    win32gui.ShowWindow(bulunan[0], win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(bulunan[0])
    except Exception:
        pass
    return True


def pencere_ac(adres: str, ortam: dict | None = None) -> None:
    if _acik_pencereyi_one_getir():
        return
    tarayici = _uygulama_tarayicisi()
    if tarayici:
        try:
            subprocess.Popen([tarayici, f"--app={adres}", "--window-size=1320,880"], env=ortam,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=not WINDOWS)
            return
        except OSError:
            pass
    webbrowser.open(adres)


# ---------- menü kısayolu (Linux, kaynaktan Windows) ----------
def linux_kisayolu_kur() -> Path:
    """Uygulama menüsüne WaveSnap ekler (~/.local/share/applications)."""
    yer = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    yer.mkdir(parents=True, exist_ok=True)
    komut = " ".join(f'"{p}"' for p in kendi_komutu())
    dosya = yer / "wavesnap.desktop"
    dosya.write_text(
        "[Desktop Entry]\nType=Application\nName=WaveSnap\n"
        "Comment=See and manage the devices on your network\n"
        f"Exec={komut}\nIcon={KAYNAK / 'web' / 'simge.png'}\nTerminal=false\nCategories=Network;Utility;\n",
        encoding="utf-8")
    dosya.chmod(0o755)
    return dosya

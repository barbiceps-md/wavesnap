# PyInstaller tarifi — Windows, macOS ve Linux için aynı dosya.
#   pyinstaller paket/wavesnap.spec --noconfirm
# Çıktı: dist/WaveSnap/ (Windows, Linux) ya da dist/WaveSnap.app (macOS)
import sys
from pathlib import Path

KOK = Path(SPECPATH).parent
sys.path.insert(0, str(KOK))
from sistem import SURUM  # noqa: E402

WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"

a = Analysis(
    [str(KOK / "wavesnap.py")],
    pathex=[str(KOK)],
    datas=[(str(KOK / "web"), "web"), (str(KOK / "veri"), "veri")],
    hiddenimports=["sunucu", "acilir"],
    excludes=["kisayol_kur", "demo", "PIL", "numpy", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WaveSnap" if WINDOWS or MAC else "wavesnap",
    console=False,
    icon=str(KOK / ("web/simge.ico" if WINDOWS else "paket/simge.icns")) if (WINDOWS or MAC) else None,
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="WaveSnap", upx=False)

if MAC:
    app = BUNDLE(
        coll,
        name="WaveSnap.app",
        icon=str(KOK / "paket" / "simge.icns"),
        bundle_identifier="io.github.barbiceps-md.wavesnap",
        info_plist={
            "CFBundleName": "WaveSnap",
            "CFBundleDisplayName": "WaveSnap",
            "CFBundleShortVersionString": SURUM,
            "CFBundleVersion": SURUM,
            # pencere tarayıcıda açılır; bu işlem yalnız arka plan sunucusu: Dock'ta simge gösterme
            "LSUIElement": True,
            "NSHumanReadableCopyright": "MIT License",
        },
    )

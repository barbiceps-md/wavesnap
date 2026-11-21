"""WaveSnap'i başlatır (masaüstü simgesi, Başlat menüsü, uygulama paketi hep bunu çalıştırır).

Sunucu zaten çalışıyorsa yalnız pencereyi açar; çalışmıyorsa sunucuyu başlatır ve pencereyi açar.
Pencere kapansa da sunucu arka planda kalır (yeni cihaz bildirimi için). Ayarlar > Paneli tamamen kapat ile durur.

    wavesnap                    pencereyi aç (gerekirse sunucuyu başlat)
    wavesnap --background       yalnız sunucuyu başlat, pencere açma
    wavesnap --install-shortcut Linux uygulama menüsüne ekle
    wavesnap --quit             arka planda çalışanı kapat (kaldırıcı ve güncelleme bunu kullanır)
    wavesnap --version
"""
import os
import socket
import sys
import threading
import time
from pathlib import Path

if not getattr(sys, "frozen", False):
    os.chdir(Path(__file__).resolve().parent)
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import sistem  # noqa: E402

ADRES = "http://127.0.0.1:8765/"


def calisiyor() -> bool:
    try:
        socket.create_connection(("127.0.0.1", 8765), timeout=0.5).close()
        return True
    except OSError:
        return False


def main():
    arguman = sys.argv[1:]
    if arguman[:1] == ["--popup"]:  # bildirimler kapalıyken kendi bildirim kutumuz (ayrı işlem)
        import acilir
        acilir.goster(*arguman[1:3])
        return
    if "--version" in arguman:
        print("WaveSnap", sistem.SURUM)
        return
    if "--quit" in arguman:
        if calisiyor():
            import urllib.request
            istek = urllib.request.Request(ADRES + "api/kapat", data=b"{}", method="POST",
                                           headers={"X-Panel": "1", "Content-Type": "application/json"})
            try:
                urllib.request.urlopen(istek, timeout=15).read()
            except OSError:
                pass
            for _ in range(50):
                if not calisiyor():
                    break
                time.sleep(0.1)
        return
    if "--install-shortcut" in arguman:
        if sistem.LINUX:
            print("added:", sistem.linux_kisayolu_kur())
        elif sistem.WINDOWS and not sistem.PAKETLI:
            import kisayol_kur
            kisayol_kur.hepsini_kur()
        else:
            print("Nothing to do: the installer or app bundle already adds WaveSnap to your menu.")
        return
    pencere = "--background" not in arguman and "--arka" not in arguman

    if calisiyor():
        if pencere:
            sistem.pencere_ac(ADRES)
        return

    import sunucu

    def bekle_ve_ac():
        for _ in range(50):
            if calisiyor():
                break
            time.sleep(0.1)
        sistem.pencere_ac(ADRES)

    if pencere:
        sunucu.panel.kalp()  # pencere birazdan açılacak: ilk okumada oturumu kapatma
        threading.Thread(target=bekle_ve_ac, daemon=True).start()
    sunucu.calistir()


if __name__ == "__main__":
    main()

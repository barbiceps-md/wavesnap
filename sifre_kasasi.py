"""Modem şifresini işletim sisteminin kendi kasasında saklar.

Windows: DPAPI — yalnız bu Windows kullanıcısının oturumunda çözülebilir (kasa.bin).
macOS: Anahtar Zinciri (Keychain). Linux: Secret Service (GNOME Anahtarlığı / KWallet).
Linux'ta anahtarlık yoksa son çare olarak yalnız bu kullanıcının okuyabildiği bir dosya (kasa.json, izin 600).
"""
import json
import logging
import os

import sistem

VERI_KLASORU = sistem.VERI
KASA = VERI_KLASORU / ("kasa.bin" if sistem.WINDOWS else "kasa.json")
ISARET = VERI_KLASORU / "kasa.anahtarlik"  # şifre işletim sisteminin anahtarlığında (Windows dışı)
SERVIS, HESAP = "WaveSnap", "modem"


def _anahtarlik():
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def kaydet(kullanici: str, sifre: str) -> None:
    VERI_KLASORU.mkdir(parents=True, exist_ok=True)
    ham = json.dumps({"k": kullanici, "s": sifre})
    if sistem.WINDOWS:
        import win32crypt
        KASA.write_bytes(win32crypt.CryptProtectData(ham.encode("utf-8"), "WaveSnap", None, None, None, 0))
        return
    k = _anahtarlik()
    if k:
        try:
            k.set_password(SERVIS, HESAP, ham)
            ISARET.write_text("", encoding="utf-8")
            if KASA.exists():
                KASA.unlink()
            return
        except Exception:
            logging.getLogger("panel").warning("anahtarlık kullanılamadı, şifre dosyada (izin 600)", exc_info=True)
    fd = os.open(KASA, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(ham)


def oku():
    """(kullanici, sifre) döner; kayıt yoksa None."""
    if sistem.WINDOWS:
        if not KASA.exists():
            return None
        import win32crypt
        _, ham = win32crypt.CryptUnprotectData(KASA.read_bytes(), None, None, None, 0)
        veri = json.loads(ham.decode("utf-8"))
    elif ISARET.exists():
        k = _anahtarlik()
        ham = k.get_password(SERVIS, HESAP) if k else None
        if not ham:
            return None
        veri = json.loads(ham)
    elif KASA.exists():
        veri = json.loads(KASA.read_text(encoding="utf-8"))
    else:
        return None
    return veri["k"], veri["s"]


def var_mi() -> bool:
    return KASA.exists() or ISARET.exists()


def sil() -> None:
    if ISARET.exists():
        k = _anahtarlik()
        try:
            if k:
                k.delete_password(SERVIS, HESAP)
        except Exception:
            pass
        ISARET.unlink()
    if KASA.exists():
        KASA.unlink()

"""İlk kurulumda modemi bulur ve tanır (şifre kullanmadan)."""
import re
import sys

from . import TAM, Genel
from .genel import _calistir, upnp_bul


def ag_gecidi() -> str:
    """Bu bilgisayarın varsayılan ağ geçidi (genelde modem)."""
    if sys.platform == "win32":
        m = re.search(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", _calistir(["route", "print", "-4", "0.0.0.0"]), re.M)
    elif sys.platform.startswith("linux"):
        m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", _calistir(["ip", "route", "show", "default"]))
    else:
        m = re.search(r"gateway:\s*(\d+\.\d+\.\d+\.\d+)", _calistir(["route", "-n", "get", "default"]))
    return m.group(1) if m else ""


def tani(host: str = "") -> dict:
    host = host or ag_gecidi() or "192.168.1.1"
    u = upnp_bul(host) or {}
    eslesen = next((s for s in TAM if s.tani(host)), None)
    return {
        "adres": host,
        "model": " ".join(x for x in (u.get("uretici"), u.get("model")) if x),
        "surucu": eslesen.KIMLIK if eslesen else Genel.KIMLIK,
        "surucu_ad": eslesen.AD if eslesen else "",
        "tanindi": bool(eslesen),
        "upnp": bool(u),
        "secenekler": [{"kimlik": s.KIMLIK, "ad": s.AD, "giris": s.GIRIS_GEREKIR} for s in (*TAM, Genel)],
    }

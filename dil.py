"""Sunucu tarafı çeviri: Windows bildirimleri ve CSV gibi ekrandan geçmeyen metinler için.

Arayüzle aynı sözlüğü (web/dil/<kod>.json) ve aynı kalıp kurallarını kullanır; bkz. web/ceviri.js.
"""
import json
import re
from pathlib import Path

KLASOR = Path(__file__).resolve().parent / "web" / "dil"
_dil = "tr"
_tam: dict = {}
_kalip: list = []


def diller() -> list:
    """[(kod, kendi dilindeki adı, bayrak dosyası)] — Türkçe kaynak dildir, sözlük dosyası yoktur.
    Bayrak: web/bayrak/<__bayrak>.svg (yoksa dil kodu)."""
    liste = [("tr", "Türkçe", "tr")]
    for f in sorted(KLASOR.glob("*.json")):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
            liste.append((f.stem, s.get("__ad", f.stem), s.get("__bayrak", f.stem)))
        except (OSError, ValueError):
            pass
    return sorted(liste, key=lambda x: (x[0] != "en", x[1]))  # varsayılan dil (İngilizce) başta


def var_mi(kod: str) -> bool:
    return kod == "tr" or (re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", kod or "") and (KLASOR / f"{kod}.json").exists())


def ayarla(kod: str):
    global _dil, _tam, _kalip
    _dil, _tam, _kalip = "tr", {}, []
    if not kod or kod == "tr" or not var_mi(kod):
        return
    sozluk = json.loads((KLASOR / f"{kod}.json").read_text(encoding="utf-8"))
    for k, v in sozluk.items():
        if k.startswith("__"):
            continue
        if "{" in k:
            adlar = re.findall(r"\{(\w+)\}", k)
            desen = "^" + re.sub(r"\\\{(\w+)\\\}", "(.+?)", re.escape(k)) + "$"
            _kalip.append((re.compile(desen, re.S), adlar, v))
        else:
            _tam[k] = v
    _kalip.sort(key=lambda x: -len(x[0].pattern))
    _dil = kod


def t(metin: str, derinlik: int = 0) -> str:
    if _dil == "tr" or not metin:
        return metin
    cekirdek = metin.strip()
    if cekirdek in _tam:
        return metin.replace(cekirdek, _tam[cekirdek])
    if derinlik < 3:
        for desen, adlar, hedef in _kalip:
            m = desen.match(cekirdek)
            if m:
                sonuc = hedef
                for i, ad in enumerate(adlar):
                    sonuc = sonuc.replace("{" + ad + "}", t(m.group(i + 1), derinlik + 1))
                return metin.replace(cekirdek, sonuc)
    return metin

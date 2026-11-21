"""Çeviri için arayüzdeki Türkçe metinleri çıkarır ve bir sözlükte eksik olanları listeler.

Kullanım:
    python araclar/metin_cikar.py               -> bütün aday metinler
    python araclar/metin_cikar.py web/dil/en.json  -> yalnız o sözlükte karşılığı olmayanlar

JavaScript dizgeleri (", ', `) basit bir tarayıcıyla okunur; şablonlardaki ${...} parçaları {0}, {1} ... olur.
HTML'de etiketler arası metinler ve placeholder/title değerleri alınır.
"""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
TURKCE = re.compile(r"[çğıöşüÇĞİÖŞÜ]|\b(ve|bir|bu|için|ile|yok|var|gün|saat|dk|sn|cihaz|ağ|hız|internet|modem|kapalı|açık)\b", re.I)


def js_dizgeler(kod):
    i, n, cikti = 0, len(kod), []
    while i < n:
        c = kod[i]
        if c == "/" and kod[i:i + 2] == "//":
            i = kod.find("\n", i)
            i = n if i < 0 else i
            continue
        if c == "/" and kod[i:i + 2] == "/*":
            i = kod.find("*/", i) + 2
            continue
        if c in "\"'":
            j, parca = i + 1, []
            while j < n and kod[j] != c:
                if kod[j] == "\\":
                    parca.append(kod[j + 1]); j += 2; continue
                parca.append(kod[j]); j += 1
            cikti.append("".join(parca)); i = j + 1
            continue
        if c == "`":
            j, parca, sayac = i + 1, [], 0
            while j < n and kod[j] != "`":
                if kod[j] == "\\":
                    parca.append(kod[j + 1]); j += 2; continue
                if kod[j:j + 2] == "${":
                    derin, k = 1, j + 2
                    while k < n and derin:
                        derin += {"{": 1, "}": -1}.get(kod[k], 0); k += 1
                    parca.append("{" + str(sayac) + "}"); sayac += 1; j = k
                    continue
                parca.append(kod[j]); j += 1
            cikti.append("".join(parca)); i = j + 1
            continue
        i += 1
    return cikti


class HtmlMetin(HTMLParser):
    def __init__(self):
        super().__init__()
        self.metinler, self.atla = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg"):
            self.atla += 1
        for k, v in attrs:
            if k in ("placeholder", "title", "aria-label", "alt") and v:
                self.metinler.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg"):
            self.atla -= 1

    def handle_data(self, data):
        if not self.atla and data.strip():
            self.metinler.append(data.strip())


def adaylar():
    sonuc = []
    for f in ("web/app.js", "web/sayfalar.js"):
        sonuc += js_dizgeler((KOK / f).read_text(encoding="utf-8"))
    h = HtmlMetin()
    h.feed((KOK / "web/index.html").read_text(encoding="utf-8"))
    sonuc += h.metinler
    temiz = []
    for m in sonuc:
        m = m.strip()
        if len(m) < 2 or not TURKCE.search(m) or re.match(r"^[#./]|^i-|^/api", m):
            continue
        if m not in temiz:
            temiz.append(m)
    return temiz


if __name__ == "__main__":
    liste = adaylar()
    if len(sys.argv) > 1:
        sozluk = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        liste = [m for m in liste if m not in sozluk]
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(liste, ensure_ascii=False, indent=1))
    print(len(liste), "metin", file=sys.stderr)

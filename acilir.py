"""Sistem bildirimleri kapalıyken (ya da yokken) kullanılan kendi bildirim kutumuz.

Ekranın sağ altında koyu bir kutu çıkar; 12 sn sonra ya da tıklayınca kaybolur.
Ayrı bir işlemde çalışır: wavesnap --popup "Başlık" "Metin"
"""
import sys

ZEMIN, CIZGI, YAZI, SOLUK, VURGU = "#1f2329", "#353b45", "#ece8e0", "#a9a69e", "#d9a55b"
GEN = 360
YAZI_TIPI = "Segoe UI" if sys.platform == "win32" else "Helvetica"


def goster(baslik: str = "WaveSnap", metin: str = "") -> None:
    import tkinter as tk

    kok = tk.Tk()
    kok.overrideredirect(True)
    kok.attributes("-topmost", True)
    kok.attributes("-alpha", 0.0)
    kok.configure(bg=CIZGI)

    ic = tk.Frame(kok, bg=ZEMIN, padx=18, pady=14)
    ic.pack(padx=1, pady=1, fill="both")
    ust = tk.Frame(ic, bg=ZEMIN)
    ust.pack(fill="x")
    tk.Label(ust, text="●", fg=VURGU, bg=ZEMIN, font=(YAZI_TIPI, 10)).pack(side="left")
    tk.Label(ust, text="  WaveSnap", fg=SOLUK, bg=ZEMIN, font=(YAZI_TIPI, 9)).pack(side="left")
    tk.Label(ic, text=baslik, fg=YAZI, bg=ZEMIN, font=(YAZI_TIPI, 12, "bold"), anchor="w").pack(fill="x", pady=(6, 0))
    tk.Label(ic, text=metin, fg=SOLUK, bg=ZEMIN, font=(YAZI_TIPI, 10), anchor="w", justify="left",
             wraplength=GEN - 40).pack(fill="x", pady=(2, 0))

    kok.update_idletasks()
    yuk = kok.winfo_reqheight()
    # görev çubuğunu hesaba katan çalışma alanı
    try:
        import ctypes
        from ctypes import wintypes
        alan = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(alan), 0)  # SPI_GETWORKAREA
        sag, alt = alan.right, alan.bottom
    except Exception:
        sag, alt = kok.winfo_screenwidth(), kok.winfo_screenheight() - 48
    x, y = sag - GEN - 16, alt - yuk - 16
    kok.geometry(f"{GEN}x{yuk}+{x}+{y + 20}")

    def belir(adim=0):
        if adim <= 10:
            kok.attributes("-alpha", adim / 10 * 0.97)
            kok.geometry(f"{GEN}x{yuk}+{x}+{y + 20 - adim * 2}")
            kok.after(18, belir, adim + 1)

    def kaybol(adim=10):
        if adim >= 0:
            kok.attributes("-alpha", adim / 10 * 0.97)
            kok.after(25, kaybol, adim - 1)
        else:
            kok.destroy()

    def tikla(_):
        kok.unbind_all("<Button-1>")
        kaybol()


    kok.bind_all("<Button-1>", tikla)
    kok.after(30, belir)
    kok.after(12000, kaybol)
    kok.mainloop()


if __name__ == "__main__":
    goster(*sys.argv[1:3])

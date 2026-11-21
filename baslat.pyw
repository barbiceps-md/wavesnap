"""Eski kısayollar için: WaveSnap artık wavesnap.py'den başlar."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().with_name("wavesnap.py")), run_name="__main__")

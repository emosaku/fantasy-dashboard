"""Streamlit runs app/Home.py with app/ itself on sys.path, so app modules import
each other as top-level names (`from categories import ...`). Match that here."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

"""Web-researched pre-trade prompt; no local price-history collection."""

from pathlib import Path

VERSION = "quant-web-v3"
PROMPT = (Path(__file__).resolve().parents[1] / "prompts/quant_entry_ko.txt").read_text()

"""Currency and payment-format codes must show their names on a machine without data/processed/."""
from __future__ import annotations

from pathlib import Path
import sys

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from api import label_maps  # noqa: E402


def test_names_come_from_the_committed_contract_maps(monkeypatch, tmp_path):
    monkeypatch.delenv("RINGSHIELD_CURRENCY_MAP", raising=False)
    monkeypatch.delenv("RINGSHIELD_PAYMENT_FORMAT_MAP", raising=False)
    monkeypatch.chdir(tmp_path)                      # no data/processed/ here
    label_maps._reverse_map.cache_clear()
    assert label_maps.currency_label(0) == "US Dollar"
    assert label_maps.payment_format_label(3) != "Format 3"


def test_a_flat_map_named_by_the_environment_still_works(monkeypatch, tmp_path):
    flat = tmp_path / "currency.json"
    flat.write_text('{"Testmark": 7}', encoding="utf-8")
    monkeypatch.setenv("RINGSHIELD_CURRENCY_MAP", str(flat))
    label_maps._reverse_map.cache_clear()
    assert label_maps.currency_label(7) == "Testmark"
    assert label_maps.currency_label(8) == "Currency 8"

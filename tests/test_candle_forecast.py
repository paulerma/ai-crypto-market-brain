import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from candle_forecast import candle_time_text, infer_candle_onset, best_candle_candidate


def test_candle_time_text():
    assert candle_time_text("15m", 3) == "45 min"
    assert candle_time_text("1h", 3) == "3 h"
    assert candle_time_text("1D", 3) == "3 días"


def test_onset_requires_persistence():
    rows = [
        {"ok": True, "bars": 1, "dominant": "LATERAL", "probability": .52, "margin": .09, "reliability": "MEDIA"},
        {"ok": True, "bars": 2, "dominant": "SUBIDA", "probability": .58, "margin": .11, "reliability": "MEDIA"},
        {"ok": True, "bars": 3, "dominant": "SUBIDA", "probability": .61, "margin": .15, "reliability": "MEDIA"},
    ]
    c = infer_candle_onset(rows, "SUBIDA")
    assert c is not None
    assert c["start_bar"] == 2
    assert c["end_bar"] == 2


def test_weak_single_horizon_is_rejected():
    rows = [
        {"ok": True, "bars": 1, "dominant": "SUBIDA", "probability": .48, "margin": .07, "reliability": "MEDIA"},
        {"ok": True, "bars": 2, "dominant": "LATERAL", "probability": .50, "margin": .08, "reliability": "MEDIA"},
    ]
    assert infer_candle_onset(rows, "SUBIDA") is None


def test_best_prefers_directional_candidate():
    rows = [
        {"ok": True, "bars": 1, "dominant": "LATERAL", "probability": .55, "margin": .12, "reliability": "MEDIA"},
        {"ok": True, "bars": 2, "dominant": "LATERAL", "probability": .54, "margin": .10, "reliability": "MEDIA"},
        {"ok": True, "bars": 3, "dominant": "BAJADA", "probability": .60, "margin": .15, "reliability": "ALTA"},
    ]
    c = best_candle_candidate(rows)
    assert c is not None
    assert c["scenario"] == "BAJADA"

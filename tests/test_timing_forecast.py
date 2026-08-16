import sys
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from timing_forecast import scenario_from_probs, infer_transition, reliability_level


def test_scenario_from_probs_returns_margin():
    name, p, margin = scenario_from_probs(.62, .23, .15)
    assert name == "SUBIDA"
    assert abs(p - .62) < 1e-9
    assert abs(margin - .39) < 1e-9


def test_transition_detects_first_reliable_change_window():
    rows = [
        {"end_hours": 3, "dominant": "LATERAL", "probability": .55, "margin": .12, "reliability": "MEDIA"},
        {"end_hours": 6, "dominant": "LATERAL", "probability": .51, "margin": .08, "reliability": "MEDIA"},
        {"end_hours": 12, "dominant": "SUBIDA", "probability": .61, "margin": .18, "reliability": "MEDIA"},
        {"end_hours": 24, "dominant": "SUBIDA", "probability": .58, "margin": .12, "reliability": "MEDIA"},
    ]
    now = datetime(2026, 8, 15, 20, 0, tzinfo=timezone.utc)
    t = infer_transition(rows, now)
    assert t is not None
    assert t["scenario"] == "SUBIDA"
    assert t["start_hours"] == 6
    assert t["end_hours"] == 12


def test_transition_refuses_weak_change():
    rows = [
        {"end_hours": 3, "dominant": "LATERAL", "probability": .55, "margin": .12, "reliability": "MEDIA"},
        {"end_hours": 12, "dominant": "BAJADA", "probability": .41, "margin": .03, "reliability": "BAJA"},
    ]
    now = datetime(2026, 8, 15, 20, 0, tzinfo=timezone.utc)
    assert infer_transition(rows, now) is None


def test_reliability_never_high_without_oos_validation():
    r = {"ok": True, "model_validated": False}
    assert reliability_level(r) == "BAJA"

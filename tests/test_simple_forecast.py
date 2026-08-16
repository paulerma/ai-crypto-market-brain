import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import pandas as pd

from simple_forecast import build_simple_forecast


def _df(n=50):
    close = np.linspace(95, 100, n)
    return pd.DataFrame({
        "high": close + 1.0,
        "low": close - 1.0,
    })


def test_simple_forecast_zones_are_ordered():
    f = build_simple_forecast(_df(), 100.0, .55, .25, .20, 94.0, 108.0, 2.0, 12)
    assert f.up.low > 100 and f.up.high > f.up.low
    assert f.flat.low < 100 < f.flat.high
    assert f.down.low < f.down.high < 100
    assert f.dominant == "SUBIDA"


def test_conditional_stops_are_on_correct_side():
    f = build_simple_forecast(_df(), 100.0, .40, .20, .40, 90.0, 112.0, 2.0, 24)
    assert f.long_plan.stop < f.long_plan.confirmation
    assert f.short_plan.stop > f.short_plan.confirmation


def test_missing_band_falls_back_without_crashing():
    f = build_simple_forecast(_df(), 100.0, .2, .6, .2, None, None, 2.0, 4)
    assert f.flat.low < 100 < f.flat.high
    assert f.dominant == "LATERAL"

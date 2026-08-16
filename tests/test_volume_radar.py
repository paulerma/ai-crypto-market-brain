import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from volume_radar import analyze_volume, direction_label, volume_alignment


def row(**kw):
    base = dict(
        vol_rel_20=1.0, volume_z_50=0.0, trades_rel_20=1.0,
        quote_vol_rel_20=1.0, taker_buy_ratio=0.50, taker_imbalance=0.0,
        cmf_20=0.0, obv_norm=0.0, vwap_dist=0.0, mfi_14=50.0,
        avg_trade_quote_rel_20=1.0,
    )
    base.update(kw)
    return base


def test_direction_labels():
    assert direction_label("SUBIDA") == "LONG"
    assert direction_label("BAJADA") == "SHORT"
    assert direction_label("LATERAL") == "LATERAL"


def test_buyer_volume_radar():
    r = analyze_volume(row(vol_rel_20=1.8, volume_z_50=1.7, trades_rel_20=1.5,
                           quote_vol_rel_20=1.7, taker_buy_ratio=.68, taker_imbalance=.36,
                           cmf_20=.18, obv_norm=1.2, vwap_dist=.012, mfi_14=67))
    assert r.direction == "COMPRADOR"
    assert r.intensity >= 60
    assert r.pressure > 0
    assert "LONG" in volume_alignment("LONG", r)


def test_seller_volume_radar():
    r = analyze_volume(row(vol_rel_20=1.7, volume_z_50=1.5, trades_rel_20=1.4,
                           quote_vol_rel_20=1.6, taker_buy_ratio=.31, taker_imbalance=-.38,
                           cmf_20=-.17, obv_norm=-1.1, vwap_dist=-.012, mfi_14=33))
    assert r.direction == "VENDEDOR"
    assert r.intensity >= 55
    assert r.pressure < 0
    assert "SHORT" in volume_alignment("SHORT", r)


def test_neutral_low_volume():
    r = analyze_volume(row(vol_rel_20=.6, trades_rel_20=.7, quote_vol_rel_20=.65))
    assert r.direction == "NEUTRAL"
    assert r.intensity < 45
    assert volume_alignment("LATERAL", r) == "COMPATIBLE CON LATERAL"

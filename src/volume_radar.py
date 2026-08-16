"""Simple, explainable volume-flow radar built from CLOSED-candle features.

It is intentionally descriptive rather than clairvoyant: it detects whether
participation/aggression is already increasing and whether that flow is more
buyer- or seller-led. It never claims to know that future volume will arrive.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


def _finite(value, default=0.0):
    try:
        x = float(value)
        return x if math.isfinite(x) else float(default)
    except Exception:
        return float(default)


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


@dataclass(frozen=True)
class VolumeRadar:
    direction: str          # COMPRADOR / VENDEDOR / NEUTRAL
    intensity: int          # 0..100 participation/activity
    pressure: int           # -100..100 seller..buyer
    phase: str              # FUERTE / ENTRANDO / NORMAL / BAJO
    rel_volume: float
    trades_rel: float
    taker_buy_ratio: float | None
    reasons: tuple[str, ...]


def analyze_volume(row) -> VolumeRadar:
    """Classify volume flow from a latest CLOSED-candle feature row."""
    vol_rel = _finite(row.get("vol_rel_20", 1.0), 1.0)
    z = _finite(row.get("volume_z_50", 0.0), 0.0)
    trades_rel = _finite(row.get("trades_rel_20", 1.0), 1.0)
    quote_rel = _finite(row.get("quote_vol_rel_20", vol_rel), vol_rel)
    taker_ratio_raw = row.get("taker_buy_ratio", float("nan"))
    taker_ratio = _finite(taker_ratio_raw, 0.5)
    taker_imb = _finite(row.get("taker_imbalance", 2 * taker_ratio - 1), 0.0)
    cmf = _finite(row.get("cmf_20", 0.0), 0.0)
    obv = _finite(row.get("obv_norm", 0.0), 0.0)
    vwap = _finite(row.get("vwap_dist", 0.0), 0.0)
    mfi = _finite(row.get("mfi_14", 50.0), 50.0)
    avg_trade_rel = _finite(row.get("avg_trade_quote_rel_20", 1.0), 1.0)

    # Participation/activity. Multiple independent proxies reduce dependence on
    # a single raw-volume spike.
    activity = (
        32 * _clip((vol_rel - 0.75) / 0.85, 0, 1)
        + 22 * _clip((quote_rel - 0.75) / 0.85, 0, 1)
        + 20 * _clip((trades_rel - 0.80) / 0.70, 0, 1)
        + 14 * _clip((z + 0.25) / 2.25, 0, 1)
        + 12 * _clip((avg_trade_rel - 0.80) / 0.70, 0, 1)
    )
    intensity = int(round(_clip(activity, 0, 100)))

    # Signed pressure: positive buyer aggression, negative seller aggression.
    raw_pressure = (
        42 * _clip(taker_imb, -1, 1)
        + 22 * _clip(cmf / 0.25, -1, 1)
        + 12 * _clip(obv / 2.0, -1, 1)
        + 10 * _clip(vwap / 0.015, -1, 1)
        + 8 * _clip((mfi - 50) / 30, -1, 1)
        + 6 * _clip((avg_trade_rel - 1.0) * (1 if taker_imb >= 0 else -1) / 0.40, -1, 1)
    )
    # When participation is tiny, directional microstructure should carry less
    # weight in the user-facing result.
    pressure = int(round(_clip(raw_pressure * (0.45 + 0.55 * intensity / 100), -100, 100)))

    if pressure >= 15:
        direction = "COMPRADOR"
    elif pressure <= -15:
        direction = "VENDEDOR"
    else:
        direction = "NEUTRAL"

    # "ENTRANDO" means participation proxies are accelerating, not that future
    # volume is guaranteed to arrive.
    accelerating = (trades_rel >= 1.10 or quote_rel >= 1.10 or z >= 0.75) and intensity >= 42
    if intensity >= 70:
        phase = "FUERTE"
    elif accelerating:
        phase = "ENTRANDO"
    elif intensity >= 35:
        phase = "NORMAL"
    else:
        phase = "BAJO"

    reasons = []
    if vol_rel >= 1.20:
        reasons.append(f"volumen {vol_rel:.1f}× su media")
    elif vol_rel <= 0.80:
        reasons.append("volumen por debajo de su media")
    if trades_rel >= 1.15:
        reasons.append(f"operaciones {trades_rel:.1f}× su media")
    if taker_ratio_raw is not None and math.isfinite(_finite(taker_ratio_raw, float('nan'))):
        reasons.append(f"taker buys {taker_ratio*100:.0f}%")
    if cmf >= 0.08:
        reasons.append("flujo de dinero positivo")
    elif cmf <= -0.08:
        reasons.append("flujo de dinero negativo")
    if not reasons:
        reasons.append("participación sin desequilibrio claro")

    return VolumeRadar(
        direction=direction,
        intensity=intensity,
        pressure=pressure,
        phase=phase,
        rel_volume=vol_rel,
        trades_rel=trades_rel,
        taker_buy_ratio=taker_ratio if math.isfinite(taker_ratio) else None,
        reasons=tuple(reasons[:4]),
    )


def direction_label(scenario: str) -> str:
    return {"SUBIDA": "LONG", "BAJADA": "SHORT", "LATERAL": "LATERAL"}.get(str(scenario), "N/A")


def volume_alignment(direction: str, radar: VolumeRadar) -> str:
    """Human-readable alignment between market bias and current volume flow."""
    if direction == "LONG":
        if radar.direction == "COMPRADOR" and radar.intensity >= 45:
            return "CONFIRMA LONG"
        if radar.direction == "VENDEDOR" and radar.intensity >= 45:
            return "CONTRADICE LONG"
        return "LONG SIN CONFIRMACIÓN DE VOLUMEN"
    if direction == "SHORT":
        if radar.direction == "VENDEDOR" and radar.intensity >= 45:
            return "CONFIRMA SHORT"
        if radar.direction == "COMPRADOR" and radar.intensity >= 45:
            return "CONTRADICE SHORT"
        return "SHORT SIN CONFIRMACIÓN DE VOLUMEN"
    if radar.direction == "NEUTRAL" or radar.intensity < 45:
        return "COMPATIBLE CON LATERAL"
    return "VOLUMEN PODRÍA PREPARAR RUPTURA"

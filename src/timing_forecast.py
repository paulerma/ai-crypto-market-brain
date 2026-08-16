"""Helpers for translating cumulative horizon forecasts into human time windows.

This module never claims an exact turning point. It identifies the *first
cumulative horizon* where a new scenario becomes dominant with enough margin
and reliability, and expresses the transition as a window between the prior
and current horizon boundaries.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
import math


@dataclass(frozen=True)
class TimingSpec:
    key: str
    label: str
    timeframe: str
    interval: str
    horizon_bars: int
    end_hours: int
    history_bars: int


# Multi-resolution design: use finer candles for near-term timing and coarser
# candles for multi-day timing instead of trying to predict 7 days with 5m bars.
TIMING_SPECS = [
    TimingSpec("3h", "Hasta 3 h", "15m", "15m", 12, 3, 3000),
    TimingSpec("6h", "Hasta 6 h", "15m", "15m", 24, 6, 3000),
    TimingSpec("12h", "Hasta 12 h", "1h", "1h", 12, 12, 2200),
    TimingSpec("24h", "Hasta 24 h", "1h", "1h", 24, 24, 2200),
    TimingSpec("72h", "Hasta 3 días", "4h", "4h", 18, 72, 1700),
    TimingSpec("168h", "Hasta 7 días", "1D", "1d", 7, 168, 1000),
]

DAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTH_NAMES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
               "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def local_dt_text(dt: datetime, include_time: bool = True) -> str:
    day = DAY_NAMES[dt.weekday()]
    month = MONTH_NAMES[dt.month - 1]
    if include_time:
        return f"{day} {dt.day} de {month}, {dt.strftime('%H:%M')}"
    return f"{day} {dt.day} de {month}"


def scenario_from_probs(p_up: float, p_flat: float, p_down: float) -> tuple[str, float, float]:
    vals = {"SUBIDA": float(p_up), "LATERAL": float(p_flat), "BAJADA": float(p_down)}
    ordered = sorted(vals.items(), key=lambda kv: kv[1], reverse=True)
    return ordered[0][0], ordered[0][1], ordered[0][1] - ordered[1][1]


def reliability_level(result: dict[str, Any]) -> str:
    """Conservative user-facing reliability bucket.

    It combines OOS quality, temporal stability, current ensemble agreement,
    calibration and analogue agreement. It intentionally refuses to call a
    forecast "high" when any major check is weak.
    """
    if not result.get("ok") or not result.get("model_validated"):
        return "BAJA"
    agreement = float(result.get("model_agreement", 0.0))
    dispersion = float(result.get("probability_dispersion", 1.0))
    analog_ok = result.get("analog_agreement")
    calibrated = bool(result.get("calibrated", False))
    skill = float(result.get("best_brier_skill", 0.0))
    bal = float(result.get("best_balanced_accuracy", 0.0))
    bal_std = float(result.get("best_balanced_accuracy_std", 1.0))

    if (result.get("quality_label") == "Sólido OOS" and calibrated and agreement >= 2/3
            and dispersion <= 0.10 and analog_ok is not False and skill >= 0.08
            and bal >= 0.43 and bal_std <= 0.08):
        return "ALTA"
    if agreement >= 2/3 and dispersion <= 0.15 and analog_ok is not False:
        return "MEDIA"
    return "BAJA"


def _scenario_persists(rows: list[dict[str, Any]], i: int, scenario: str) -> bool:
    """Require confirmation in the next horizon, unless current evidence is strong."""
    cur = rows[i]
    if i + 1 < len(rows):
        nxt = rows[i + 1]
        if nxt.get("dominant") == scenario and nxt.get("reliability") in ("MEDIA", "ALTA"):
            return True
    return bool(cur.get("reliability") == "ALTA" and cur.get("probability", 0) >= 0.55 and cur.get("margin", 0) >= 0.10)


def infer_transition(rows: list[dict[str, Any]], now_local: datetime,
                     min_probability: float = 0.45, min_margin: float = 0.06) -> dict[str, Any] | None:
    """Infer a possible scenario-change window from cumulative forecasts.

    A reliable horizon can establish/update the current baseline. A *change* to
    a new scenario must additionally persist into the next horizon (or be very
    strong on its own), which reduces one-horizon whipsaws.
    """
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: r["end_hours"])
    last_reliable_dom = None
    last_reliable_end = 0

    for i, r in enumerate(rows):
        dom = r.get("dominant")
        base_good = (r.get("reliability") in ("MEDIA", "ALTA")
                     and r.get("probability", 0) >= min_probability
                     and r.get("margin", 0) >= min_margin)
        if not base_good:
            continue

        if last_reliable_dom is None:
            # A directional scenario at the first reliable horizon is useful
            # only if it persists; otherwise keep looking.
            if dom in ("SUBIDA", "BAJADA"):
                if _scenario_persists(rows, i, dom):
                    return {
                        "scenario": dom, "start_hours": 0, "end_hours": r["end_hours"],
                        "start": now_local, "end": now_local + timedelta(hours=r["end_hours"]),
                        "probability": r["probability"], "reliability": r["reliability"],
                        "already_possible": (i == 0), "row": r,
                    }
                continue
            last_reliable_dom = dom
            last_reliable_end = r["end_hours"]
            continue

        if dom == last_reliable_dom:
            # Extend the baseline to the latest reliable boundary.
            last_reliable_end = r["end_hours"]
            continue

        # A proposed change must be confirmed by persistence.
        if _scenario_persists(rows, i, dom):
            return {
                "scenario": dom, "start_hours": last_reliable_end, "end_hours": r["end_hours"],
                "start": now_local + timedelta(hours=last_reliable_end),
                "end": now_local + timedelta(hours=r["end_hours"]),
                "probability": r["probability"], "reliability": r["reliability"],
                "already_possible": False, "row": r,
            }
    return None


def transition_text(transition: dict[str, Any] | None) -> str:
    if not transition:
        return "No aparece una ventana de cambio suficientemente fiable en los horizontes analizados."
    sc = transition["scenario"]
    if transition.get("already_possible"):
        return (f"{sc}: podría estar empezando ya y confirmarse antes de "
                f"{local_dt_text(transition['end'])}.")
    return (f"{sc}: la primera ventana donde cambia el escenario dominante es entre "
            f"{local_dt_text(transition['start'])} y {local_dt_text(transition['end'])}.")


def first_scenario_window(rows: list[dict[str, Any]], scenario: str, now_local: datetime,
                          min_probability: float = 0.45, min_margin: float = 0.06) -> dict[str, Any] | None:
    """Earliest cumulative horizon that supports a requested scenario."""
    rows = sorted(rows, key=lambda x: x["end_hours"])
    prev_end = 0
    for i, r in enumerate(rows):
        good = (r.get("dominant") == scenario
                and r.get("reliability") in ("MEDIA", "ALTA")
                and r.get("probability", 0) >= min_probability
                and r.get("margin", 0) >= min_margin
                and _scenario_persists(rows, i, scenario))
        if good:
            return {
                "scenario": scenario, "start_hours": prev_end, "end_hours": r["end_hours"],
                "start": now_local + timedelta(hours=prev_end),
                "end": now_local + timedelta(hours=r["end_hours"]),
                "probability": r["probability"], "reliability": r["reliability"], "row": r,
            }
        prev_end = r["end_hours"]
    return None

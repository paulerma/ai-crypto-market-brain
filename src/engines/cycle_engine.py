"""
CYCLE ENGINE — mide, sobre datos reales, cuánto ha durado la fase
actual y cuánto duraron fases similares en el pasado. NO asume la
duración: la calcula a partir de la propia serie de régimen generada
por regime_engine.py sobre el histórico real descargado.

El patrón de ~1,060 días entre mínimos/máximos de ciclo mencionado en
el brief se deja como constante DOCUMENTADA (no como regla) en
CYCLE_LOW_REFERENCE_DAYS / CYCLE_HIGH_REFERENCE_DAYS — es una
referencia externa citada por el usuario, no algo derivado de los
datos de este proyecto. Debe tratarse como una feature más, y su
capacidad predictiva real debe evaluarse con datos suficientes
(varios ciclos completos) antes de darle ningún peso.
"""

from dataclasses import dataclass
import pandas as pd

# Referencia citada por el usuario — NO calculada por este sistema,
# NO es una regla. Ver docstring del módulo.
CYCLE_REFERENCE_DAYS_APPROX = 1060


@dataclass
class CycleState:
    current_regime: str
    days_in_current_phase: int
    n_similar_past_phases: int
    similar_phase_duration_min: int | None
    similar_phase_duration_max: int | None
    similar_phase_duration_mean: float | None


def phase_durations(regime_series: pd.Series) -> pd.DataFrame:
    """A partir de una serie de régimen por vela (ej. la salida de
    regime_engine.regime_series), calcula CADA racha histórica real:
    régimen, duración en velas, índice de inicio/fin. Esto es la base
    real para "duración histórica de situaciones similares" — no un
    número inventado."""
    df = regime_series.reset_index(drop=True).to_frame("regime")
    df["change"] = (df["regime"] != df["regime"].shift(1)).cumsum()
    grouped = df.groupby("change")
    rows = []
    for _, g in grouped:
        rows.append({
            "regime": g["regime"].iloc[0],
            "start_idx": g.index[0],
            "end_idx": g.index[-1],
            "duration": len(g),
        })
    return pd.DataFrame(rows)


def current_cycle_state(regime_series: pd.Series) -> CycleState:
    phases = phase_durations(regime_series)
    if phases.empty:
        raise ValueError("regime_series vacía — no se puede calcular el ciclo.")

    current = phases.iloc[-1]
    current_regime = current["regime"]
    days_in_phase = int(current["duration"])

    past_same_regime = phases.iloc[:-1]
    past_same_regime = past_same_regime[past_same_regime["regime"] == current_regime]

    if past_same_regime.empty:
        return CycleState(
            current_regime=current_regime, days_in_current_phase=days_in_phase,
            n_similar_past_phases=0, similar_phase_duration_min=None,
            similar_phase_duration_max=None, similar_phase_duration_mean=None,
        )

    durations = past_same_regime["duration"]
    return CycleState(
        current_regime=current_regime, days_in_current_phase=days_in_phase,
        n_similar_past_phases=len(durations),
        similar_phase_duration_min=int(durations.min()),
        similar_phase_duration_max=int(durations.max()),
        similar_phase_duration_mean=float(durations.mean()),
    )

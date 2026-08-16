"""
PIPELINE — orquesta el flujo completo con datos REALES:

  DataEngine (CoinGecko histórico)
    -> feature_engine.build_features
    -> labeling.build_label_set (triple-barrier, ajustado por volatilidad)
    -> backtest.compare_models (walk-forward, varios modelos)
    -> selecciona el mejor modelo por Brier score fuera de muestra
    -> calibra sobre el tramo más reciente
    -> regime_engine + cycle_engine + pattern_engine (contexto real)
    -> decision_engine (probabilidad calibrada -> señal)
    -> imprime el estado tipo "AI MARKET BRAIN" + panel de calidad de datos

Uso:
    cd btc-market-brain
    cp .env.example .env        # y pega tu COINGECKO_API_KEY ahí
    pip install -r requirements.txt
    python src/pipeline.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "engines"))

import pandas as pd

from data_engine import DataEngine
from feature_engine import build_features, FEATURE_COLUMNS
from labeling import triple_barrier_labels
from backtest import compare_models, walk_forward_validate
from models import fit_model, prepare_training_frame
from calibration import calibrate
from engines.regime_engine import regime_series, classify_regime
from engines.cycle_engine import current_cycle_state
from engines.pattern_engine import find_similar_cases
from engines.decision_engine import decide, build_entry_setup
from adapters.base import DataSourceUnavailable


HORIZON_DAYS = 7          # horizonte de predicción, en velas diarias
K_ATR = 1.5                # múltiplo de ATR% para las barreras del labeling
CANDIDATE_MODELS = ["logistic_regression", "random_forest", "gradient_boosting"]


def run():
    print("=" * 60)
    print("BTC AI MARKET BRAIN — pipeline con datos reales (CoinGecko)")
    print("=" * 60)

    engine = DataEngine()

    print("\n[1/6] Descargando histórico real (CoinGecko)...")
    try:
        ohlcv = engine.get_ohlcv(symbol="BTC", vs_currency="usd", days=365, use_cache=True)
    except DataSourceUnavailable as e:
        print(f"\n❌ DATOS INCOMPLETOS — no se pudo obtener histórico real: {e}")
        print("   Revisa COINGECKO_API_KEY en tu .env y tu conexión a internet.")
        print_data_quality(engine)
        return
    print(f"   {len(ohlcv)} velas diarias descargadas/cacheadas.")

    print("\n[2/6] Calculando features reales...")
    features = build_features(ohlcv)

    print(f"\n[3/6] Etiquetando (triple-barrier, horizonte={HORIZON_DAYS} velas, k={K_ATR}×ATR)...")
    labels = triple_barrier_labels(features, horizon=HORIZON_DAYS, k=K_ATR)

    valid_n = labels.dropna().shape[0]
    print(f"   {valid_n} filas con label válido para entrenar.")
    if valid_n < 260:
        print("\n⚠️  Histórico real insuficiente para un walk-forward robusto "
              "(se recomienda >2 años de datos diarios). Los resultados de "
              "backtest de abajo deben interpretarse con MUCHA cautela.")

    print("\n[4/6] Walk-forward validation — comparando modelos reales...")
    try:
        comparison = compare_models(features, labels, FEATURE_COLUMNS, CANDIDATE_MODELS,
                                     n_folds=5, min_train_size=180)
        print(comparison.to_string(index=False))
    except ValueError as e:
        print(f"   No se pudo correr walk-forward: {e}")
        comparison = pd.DataFrame()

    if comparison.empty or "brier_score_mean" not in comparison.columns:
        print("\n❌ No hay suficientes datos/resultados para elegir modelo. Deteniendo aquí.")
        print_data_quality(engine)
        return

    comparison_valid = comparison.dropna(subset=["brier_score_mean"])
    if comparison_valid.empty:
        print("\n❌ Ningún modelo produjo un Brier score válido. Deteniendo aquí.")
        return
    best_model_name = comparison_valid.sort_values("brier_score_mean").iloc[0]["model"]
    print(f"\n   Modelo seleccionado (menor Brier score fuera de muestra): {best_model_name}")

    print("\n[5/6] Entrenando modelo final + calibración sobre el tramo más reciente...")
    X_full, y_full = prepare_training_frame(features, labels, FEATURE_COLUMNS)
    cal_start = int(len(X_full) * 0.85)
    fit_X, fit_y = X_full.iloc[:cal_start], y_full.iloc[:cal_start]
    cal_X, cal_y = X_full.iloc[cal_start:], y_full.iloc[cal_start:]

    trained = fit_model(best_model_name, fit_X, fit_y)
    try:
        calibrated_model = calibrate(trained.model, cal_X, cal_y, method="sigmoid")
        classes = list(calibrated_model.classes_)
        use_model = calibrated_model
    except Exception as e:
        print(f"   Calibración falló ({e}); se usará el modelo sin calibrar "
              f"(las probabilidades mostradas NO están calibradas — tratar con cautela extra).")
        use_model = trained.model
        classes = list(trained.classes_)

    print("\n[6/6] Generando estado actual del AI Market Brain...\n")
    last_row = features.iloc[[-1]][FEATURE_COLUMNS]
    if last_row.isna().any(axis=None):
        print("❌ La última vela tiene features incompletas (probablemente falta "
              "warm-up de algún indicador). No se genera señal para evitar un número falso.")
        print_data_quality(engine)
        return

    proba = use_model.predict_proba(last_row)[0]
    proba_map = {int(c): float(p) for c, p in zip(classes, proba)}
    p_up, p_flat, p_down = proba_map.get(1, 0.0), proba_map.get(0, 0.0), proba_map.get(-1, 0.0)

    decision = decide(p_up, p_flat, p_down)

    current_price = float(ohlcv["close"].iloc[-1])
    atr = float(features["atr_14"].iloc[-1])
    regimes = regime_series(features)
    current_regime_state = classify_regime(features.iloc[-1])

    try:
        cycle = current_cycle_state(regimes)
    except ValueError:
        cycle = None

    forward_returns = features["close"].shift(-HORIZON_DAYS) / features["close"] - 1
    similar = find_similar_cases(features, FEATURE_COLUMNS, forward_returns, HORIZON_DAYS, k=30)

    print("─" * 60)
    print(f"BTC/USD  ${current_price:,.0f}   (fuente: CoinGecko, histórico real)")
    print("─" * 60)
    print(f"🟢 SUBIR   {p_up*100:5.1f}%")
    print(f"🟡 LATERAL {p_flat*100:5.1f}%")
    print(f"🔴 BAJAR   {p_down*100:5.1f}%")
    print(f"\nHorizonte: {HORIZON_DAYS} días  |  Modelo: {best_model_name}  |  Calibrado: sigmoid (Platt)")
    print(f"DECISIÓN: {decision.signal}" + (f" ({decision.direction})" if decision.direction else ""))
    print(f"Confianza calibrada: {decision.confidence*100:.1f}%")
    print(f"\nRégimen: {current_regime_state.regime}  |  Fase: {current_regime_state.phase}")
    if cycle:
        print(f"Días en fase actual: {cycle.days_in_current_phase}  |  "
              f"Fases similares previas: {cycle.n_similar_past_phases}"
              + (f"  (duración {cycle.similar_phase_duration_min}-{cycle.similar_phase_duration_max}d, "
                 f"media {cycle.similar_phase_duration_mean:.0f}d)" if cycle.n_similar_past_phases else ""))

    if similar:
        print(f"\nCasos históricos similares (k-NN, n={similar.n_cases}, horizonte {HORIZON_DAYS}d):")
        print(f"  Subieron: {similar.up_pct:.0f}%  Lateral: {similar.flat_pct:.0f}%  "
              f"Bajaron: {similar.down_pct:.0f}%")
        print(f"  Retorno medio: {similar.mean_forward_return*100:+.1f}%  "
              f"(rango observado: {similar.min_forward_return*100:+.1f}% a "
              f"{similar.max_forward_return*100:+.1f}%)")
    else:
        print("\nCasos históricos similares: histórico real insuficiente todavía para k-NN confiable.")

    if decision.direction:
        setup = build_entry_setup(current_price, decision.direction, atr)
        print(f"\nEntry engine — zona ${setup.entry_low:,.0f}-${setup.entry_high:,.0f}  "
              f"objetivo ${setup.target:,.0f}  invalidación ${setup.invalidation:,.0f}  "
              f"R:R {setup.risk_reward:.1f}:1")

    print_data_quality(engine)


def print_data_quality(engine: DataEngine):
    print("\n" + "─" * 60)
    print("DATA STATUS")
    print("─" * 60)
    for row in engine.data_quality_report():
        icon = "🟢" if row["connected"] else "⚪"
        print(f"{icon} {row['source']}: {'LIVE/OK' if row['connected'] else 'NO CONECTADO'} "
              f"— {row['detail']}")


if __name__ == "__main__":
    run()

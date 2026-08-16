AI CRYPTO MARKET BRAIN PRO — FASE 3.0
=====================================

Qué cambia frente a Fase 2.1
----------------------------
1) 57 features cuantitativas agrupadas por:
   - Tendencia: EMA 9/20/50/100/200, SMA 20/50/100/200 y pendientes.
   - Momentum: RSI, Stoch RSI, MACD, ROC, Williams %R, CCI.
   - Fuerza de tendencia: ADX + DMI.
   - Volatilidad: ATR, ATR%, volatilidad realizada, Parkinson, Bollinger/Keltner squeeze.
   - Volumen/flujo: volumen relativo, z-score, OBV, VWAP, CMF, MFI.
   - Estructura/price action: posición en rangos, highs/lows, cuerpo y mechas.

2) Selección de features dentro de cada pipeline de entrenamiento.
   No se usan las 57 a ciegas: cada modelo selecciona variables en TRAIN para reducir overfitting.

3) Ensemble calibrado de hasta 3 modelos con mejor walk-forward.
   Candidatos: Logistic Regression, Random Forest, Gradient Boosting,
   Extra Trees e HistGradientBoosting.

4) Validación walk-forward de 5 folds y selección por Brier + F1 + accuracy.
   La probabilidad mostrada NO se sube artificialmente por agregar indicadores.

5) Confluencia técnica independiente (0-100): EMA200, EMA20/50, pendiente,
   DMI, MACD, RSI, VWAP, CMF, OBV y estructura.
   Sirve para FILTRAR señales, no para inflar la probabilidad del modelo.

6) Contexto global en vivo (pestaña Contexto global):
   - breadth de pares USDT líquidos en Binance,
   - retorno mediano y ponderado por volumen,
   - Fear & Greed cuando está disponible,
   - funding y open interest del activo cuando Binance Futures lo soporta.

7) Scanner mejorado: exige señal direccional + confianza + confluencia + R:R.
   BEST OPPORTUNITY no aparece si no cumple filtros mínimos.

8) Riesgo mejorado:
   - SL ajustado / recomendado / conservador,
   - TP1 / TP2 / TP3,
   - tamaño de posición y ganancias/pérdidas potenciales.

9) Gráfico: EMA9/20/50/200, VWAP, Bollinger, soporte/resistencia,
   señales y niveles SL/TP sobre el gráfico.

IMPORTANTE
----------
Agregar más indicadores NO garantiza mayor accuracy. Esta versión intenta mejorar
la calidad usando selección de features, ensemble, calibración y filtros de
confluencia. El criterio correcto es el resultado FUERA DE MUESTRA del backtest,
no que el número de confianza se vea más alto.

No envía órdenes reales. Úsalo primero en backtest y paper trading.

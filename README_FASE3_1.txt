AI CRYPTO MARKET BRAIN PRO — FASE 3.1 AUDITADA
==============================================

Correcciones principales después de auditoría:
1) Calibración compatible con scikit-learn moderno mediante FrozenEstimator.
2) Walk-forward PURGADO: las etiquetas que miran al futuro no cruzan la frontera train/test.
3) Métricas siempre sobre las 3 clases y Brier Skill contra baseline de climatología.
4) Gate de calidad OOS: si el modelo no demuestra ventaja, fuerza NO OPERAR.
5) Triple-barrier: velas ambiguas que tocan ambas barreras se excluyen en vez de inventar el orden.
6) Backtest coherente con triple-barrier: target/stop/horizonte + comisiones/slippage estimado.
7) MACD normalizado para reducir dependencia del nivel nominal de precio.
8) Volatilidad mostrada por 14 velas, sin anualización incorrecta en timeframes intradía.
9) Señal basada en vela cerrada; el precio visible puede ser la vela actual.
10) Volumen en panel separado para no aplastar la escala del precio.
11) Cambio 24h real adaptado al timeframe.
12) Horizonte explicado en tiempo real (ej. 12 velas de 1h = 12h).
13) Interfaz simplificada con una frase de “Lectura sencilla” y detalles técnicos plegables.
14) Scanner exige calidad OOS + confianza + confluencia + R:R.
15) Launcher elige un puerto libre y muestra errores de forma legible.

No ejecuta órdenes reales.

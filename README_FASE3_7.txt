AI CRYPTO MARKET BRAIN PRO · FASE 3.7 TODAS LAS TEMPORALIDADES

Esta versión conserva LONG / LATERAL / SHORT, Radar de Velas, Radar de Volumen,
Stop Loss, proyecciones y validación OOS, y amplía el selector de temporalidad.

TEMPORALIDADES DE TIEMPO PREDETERMINADAS DE TRADINGVIEW INCLUIDAS
Segundos: 1s, 5s, 10s, 15s, 30s, 45s
Minutos: 1m, 2m, 3m, 5m, 10m, 15m, 30m, 45m
Horas: 1h, 2h, 3h, 4h
Largo plazo: 1D, 1W, 1M, 3M, 6M, 12M

DATOS
- Cuando Binance ofrece la temporalidad de forma nativa, se usa directamente.
- 2m, 10m, 45m, 3h y los multi-meses se construyen agregando velas reales de
  Binance con reglas OHLCV correctas. No se inventan precios.
- Las temporalidades en segundos también pueden agregarse desde velas reales de 1s.

ML / IA
- El modelo estricto se habilita entre 1m y 1W, donde existe profundidad histórica
  suficiente para el esquema actual de validación.
- Segundos y 1M+ quedan disponibles para gráfico/contexto, pero no se fuerza una
  probabilidad ML si la muestra no permite una validación defendible.
- Esto evita que una temporalidad aparezca "más precisa" solo porque tiene pocos datos.

MULTI-TIMEFRAME
- Rápido: 1m, 5m, 15m, 1h, 4h, 1D, 1W.
- Completo: 1m, 2m, 3m, 5m, 10m, 15m, 30m, 45m, 1h, 2h, 3h, 4h, 1D, 1W.

NOTA
TradingView también ofrece Ticks y Range, pero no son temporalidades basadas en tiempo.
Esta versión no los mezcla con el selector de timeframes.

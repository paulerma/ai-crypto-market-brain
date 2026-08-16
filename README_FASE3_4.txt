AI CRYPTO MARKET BRAIN PRO 3.4 — PRONÓSTICO TEMPORAL MULTI-RESOLUCIÓN

OBJETIVO
Responder de forma sencilla cuatro preguntas:
1. ¿Es más probable que suba, lateralice o baje?
2. ¿En qué ventana de tiempo podría empezar/cambiar ese escenario?
3. ¿Qué zona de precio es razonable estadísticamente?
4. Si rompe al alza o a la baja, ¿qué nivel confirma y dónde queda una invalidación/stop de referencia?

MEJORAS 3.4
- Línea temporal automática hasta 7 días usando varias resoluciones:
  15m (3–6h), 1h (12–24h), 4h (3 días), 1D (7 días).
- No compara un pronóstico de 7 días usando miles de velas de 5m; usa una escala coherente con cada horizonte.
- El cambio temporal exige margen de probabilidad, calidad OOS y persistencia en el siguiente horizonte o evidencia fuerte.
- Estabilidad entre folds: el modelo ya no se considera validado solo porque el promedio sea bueno; también se penaliza si cambia demasiado de un periodo a otro.
- Ensemble real de 3 modelos en modo normal (en 3.3 el texto decía 3, pero el promedio final utilizaba 2).
- Acuerdo entre modelos y dispersión de probabilidades.
- Casos históricos parecidos corregidos: ahora el vector consultado es realmente el estado actual y se evita contar muchas velas consecutivas del mismo episodio como evidencia independiente.
- Nuevas variables públicas de Binance: volumen cotizado, número de operaciones y proporción taker-buy cuando están disponibles.
- Variables cíclicas de hora/día de la semana, conocidas en el momento de la predicción.
- La zona de precio se mantiene conservadora; si los análogos históricos confirman, se amplía para incluir ambos métodos en vez de fingir una precisión excesiva.

VALIDACIÓN
- Walk-forward purgado.
- Holdout temporal separado para calibración.
- Balanced accuracy, F1 macro, Brier score/skill.
- Variabilidad entre folds.
- 3 clases siempre: subida/lateral/bajada.
- Vela todavía abierta excluida del modelo.

INTERPRETACIÓN DEL TIEMPO
Los modelos son acumulativos (“hasta 6h”, “hasta 12h”…). La app infiere una posible ventana de cambio entre dos fronteras consecutivas cuando el escenario dominante cambia y pasa filtros conservadores. No es un detector de hora exacta.

LIMITACIONES
- Ningún modelo puede garantizar ganancias ni fechas exactas.
- Eventos de noticias, regulación, hacks y shocks de liquidez pueden invalidar una proyección inmediatamente.
- Funding/OI/breadth actuales se muestran como contexto, pero no se introducen a la probabilidad si no hay un histórico equivalente validado para evitar contaminar el modelo con señales no backtesteadas.

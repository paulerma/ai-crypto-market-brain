FASE 3.2 — PRÁCTICA / LIVE / PROYECCIONES

Cambios principales frente a 3.1:
- Modo Sencillo y Avanzado.
- Gráfico principal separado de RSI/MACD/volumen para moverlo y hacer zoom con facilidad.
- Drag por defecto = PAN; rueda/trackpad = zoom; doble clic = reset.
- uirevision para conservar zoom/posición al rerenderizar.
- Precio LIVE aproximado cada 10 s mediante endpoint público de Binance, separado del modelo.
- Señales únicamente con velas cerradas.
- Panel de proyecciones probabilísticas corto/medio/largo.
- Rango de volatilidad aproximado (~1 sigma) + barreras triple-barrier; no son targets garantizados.
- Filtro práctico adicional: modelo OOS + confianza + confluencia >=60 + R:R >=1:1.5 antes de mostrar LONG/SHORT como acción práctica.
- Scanner y MTF guardan resultados por contexto para no mezclar activos/timeframes.
- R:R se presenta en formato intuitivo 1:2, 1:3, etc.
- Menos warnings de Streamlit: width='stretch' en lugar de use_container_width.
- Main model usa 3 modelos diversos y 4 folds para mantener la app práctica; la validación sigue mostrando métricas OOS.
- Calibración final exige representación mínima de las tres clases.
- INICIAR.command detecta Python 3.10-3.14 y reinstala dependencias solo si requirements.txt cambió.

Notas:
- “LIVE” aquí significa actualización aproximada cada 10 s. No es tick-by-tick ni WebSocket de 1 segundo.
- Las proyecciones son escenarios probabilísticos y rangos estadísticos, no precios futuros garantizados.
- No se ejecutan órdenes reales.

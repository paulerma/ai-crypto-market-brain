"""
Adaptadores de Fase 2 — TODAVÍA NO CONECTADOS.

Cada clase implementa el contrato de base.py pero no tiene ninguna
fuente real detrás. Existen para que:
  1) DataEngine pueda registrar su estado como "NO CONECTADO" en el
     panel de calidad de datos, en vez de omitirlos en silencio.
  2) Cuando se decida activar Binance/derivados/on-chain/macro, solo
     haya que escribir la implementación real dentro de la clase
     correspondiente e implementar sus métodos — nada aguas abajo
     (feature engine, modelos, decisión) cambia.

REGLA DURA: ninguna de estas clases debe devolver nunca un número
inventado. Si se llama a un método antes de implementarlo con una
fuente real, debe lanzar DataSourceUnavailable.
"""

from .base import (
    LiveMarketSource, DerivativesSource, OnChainSource, MacroSource,
    SourceStatus, DataSourceUnavailable,
)


class BinanceLiveSource(LiveMarketSource):
    """Fase 2 — precio/order book/trades en vivo vía WebSocket de Binance
    (o el exchange que se decida). Requiere BINANCE_API_KEY en .env
    solo si se necesitan endpoints privados; los públicos de mercado
    no requieren key."""

    def get_ticker(self, symbol: str) -> dict:
        raise DataSourceUnavailable(
            "BinanceLiveSource no está implementado todavía (Fase 2). "
            "No se debe sustituir por un valor simulado."
        )

    def status(self) -> SourceStatus:
        return SourceStatus(name="binance_live", connected=False,
                             detail="Adaptador definido, sin implementar (Fase 2)")


class DerivativesAdapter(DerivativesSource):
    """Fase 2 — funding rate, open interest, liquidaciones, basis.
    Candidatos: Binance Futures API, Bybit, Coinalyze, Coinglass."""

    def get_derivatives_snapshot(self, symbol: str) -> dict:
        raise DataSourceUnavailable(
            "DerivativesAdapter no está implementado todavía (Fase 2)."
        )

    def status(self) -> SourceStatus:
        return SourceStatus(name="derivatives", connected=False,
                             detail="Adaptador definido, sin implementar (Fase 2)")


class OnChainAdapter(OnChainSource):
    """Fase 2 — SOPR, MVRV, realized price, exchange flows, holders.
    Candidatos: Glassnode, CryptoQuant, IntoTheBlock (todos requieren key de pago
    para métricas avanzadas; hay algunas gratuitas limitadas)."""

    def get_onchain_snapshot(self, asset: str) -> dict:
        raise DataSourceUnavailable(
            "OnChainAdapter no está implementado todavía (Fase 2)."
        )

    def status(self) -> SourceStatus:
        return SourceStatus(name="onchain", connected=False,
                             detail="Adaptador definido, sin implementar (Fase 2)")


class MacroAdapter(MacroSource):
    """Fase 2 — DXY, VIX, S&P500, tasas, liquidez.
    Candidato con capa gratuita real: FRED (Federal Reserve Economic Data),
    requiere FRED_API_KEY gratuita."""

    def get_macro_snapshot(self) -> dict:
        raise DataSourceUnavailable(
            "MacroAdapter no está implementado todavía (Fase 2)."
        )

    def status(self) -> SourceStatus:
        return SourceStatus(name="macro", connected=False,
                             detail="Adaptador definido, sin implementar (Fase 2)")

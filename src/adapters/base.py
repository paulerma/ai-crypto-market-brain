"""
Contrato común para TODOS los adaptadores de datos del sistema.

La arquitectura es deliberadamente así (pedido explícito):

    CoinGecko   -> histórico
    Exchange    -> precio/mercado en vivo (WebSocket)
    Derivados   -> funding / open interest / liquidaciones
    On-chain    -> métricas blockchain
    Macro       -> contexto macro
        |
        v
    DATA ENGINE  (normaliza todo a un esquema común)
        |
        v
    FEATURE ENGINE / MODELOS / AI MARKET BRAIN

Ningún módulo de features/modelos/decisión debe importar un adaptador
directamente. Siempre pasan por DataEngine, que expone un esquema fijo
(ver OHLCVFrame más abajo). Así, cambiar CoinGecko por Binance para el
histórico, o activar un adaptador on-chain nuevo, no obliga a tocar
nada aguas abajo.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


class DataSourceUnavailable(Exception):
    """Se lanza cuando una fuente no está conectada o falla.
    NUNCA debe capturarse para sustituir el dato por uno inventado:
    el llamador debe propagar el estado 'DATOS INCOMPLETOS'."""
    pass


@dataclass
class SourceStatus:
    name: str
    connected: bool
    detail: str = ""
    last_update: Optional[pd.Timestamp] = None


class HistoricalPriceSource(ABC):
    """Fuente de OHLCV histórico (ej. CoinGecko, Binance klines, etc.)"""

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, vs_currency: str, days: int) -> pd.DataFrame:
        """Debe devolver un DataFrame con columnas exactas:
        ['timestamp','open','high','low','close','volume']
        timestamp en UTC, tipo datetime64.
        Si la fuente no puede servir el rango pedido, debe lanzar
        DataSourceUnavailable — nunca rellenar con datos falsos.
        """
        raise NotImplementedError

    @abstractmethod
    def status(self) -> SourceStatus:
        raise NotImplementedError


class LiveMarketSource(ABC):
    """Fase 2 — precio/mercado en vivo vía WebSocket/REST de un exchange."""

    @abstractmethod
    def get_ticker(self, symbol: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> SourceStatus:
        raise NotImplementedError


class DerivativesSource(ABC):
    """Fase 2 — funding rate, open interest, liquidaciones, basis."""

    @abstractmethod
    def get_derivatives_snapshot(self, symbol: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> SourceStatus:
        raise NotImplementedError


class OnChainSource(ABC):
    """Fase 2 — SOPR, MVRV, exchange flows, actividad de holders."""

    @abstractmethod
    def get_onchain_snapshot(self, asset: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> SourceStatus:
        raise NotImplementedError


class MacroSource(ABC):
    """Fase 2 — DXY, VIX, S&P500, tasas, liquidez."""

    @abstractmethod
    def get_macro_snapshot(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> SourceStatus:
        raise NotImplementedError

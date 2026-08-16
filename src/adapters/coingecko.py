"""
Adaptador REAL — CoinGecko (fuente de HISTÓRICO, no del núcleo del sistema).

Rol en la arquitectura: únicamente alimenta al DATA ENGINE con velas
OHLC históricas para entrenar/backtestear. No se usa como fuente de
"tiempo real" — para eso está LiveMarketSource (Fase 2, adaptador de
exchange vía WebSocket). Mezclar ambos roles en una sola fuente fue
señalado explícitamente como un error a evitar.

Requiere la variable de entorno COINGECKO_API_KEY (ver .env.example).
Sin key, CoinGecko igual permite un tier gratuito muy limitado en
rate-limit; con key Demo (gratuita) el límite es más cómodo.

Este archivo NO simula nada: si la petición HTTP falla, se lanza
DataSourceUnavailable y el llamador debe manejarlo mostrando
"DATOS INCOMPLETOS" — nunca debe rellenarse con datos inventados.
"""

import os
import time
import requests
import pandas as pd
from dotenv import load_dotenv

from .base import HistoricalPriceSource, SourceStatus, DataSourceUnavailable

load_dotenv()

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COIN_ID_MAP = {"BTC": "bitcoin", "ETH": "ethereum"}


class CoinGeckoSource(HistoricalPriceSource):
    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self.api_key = api_key or os.getenv("COINGECKO_API_KEY", "").strip()
        self.timeout = timeout
        self._last_status = SourceStatus(name="coingecko", connected=False,
                                          detail="sin consultar todavía")

    def _headers(self) -> dict:
        # CoinGecko Demo keys van en el header x-cg-demo-api-key.
        if self.api_key:
            return {"x-cg-demo-api-key": self.api_key}
        return {}

    def fetch_ohlc(self, symbol: str, vs_currency: str = "usd", days: int = 365) -> pd.DataFrame:
        """Endpoint /coins/{id}/ohlc — devuelve velas [ts, open, high, low, close]
        ya agregadas por CoinGecko (sin volumen). days admite: 1,7,14,30,90,180,365,max
        (según el tier). Se ajusta automáticamente al valor soportado más cercano."""
        coin_id = COIN_ID_MAP.get(symbol.upper(), symbol.lower())
        allowed_days = [1, 7, 14, 30, 90, 180, 365, "max"]
        days_param = days if days in allowed_days else min(
            (d for d in allowed_days if isinstance(d, int)), key=lambda d: abs(d - days)
        )
        url = f"{COINGECKO_BASE}/coins/{coin_id}/ohlc"
        params = {"vs_currency": vs_currency, "days": days_param}
        try:
            resp = requests.get(url, params=params, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as e:
            self._last_status = SourceStatus(name="coingecko", connected=False, detail=str(e))
            raise DataSourceUnavailable(f"CoinGecko OHLC request failed: {e}") from e

        if resp.status_code != 200:
            self._last_status = SourceStatus(
                name="coingecko", connected=False,
                detail=f"HTTP {resp.status_code}: {resp.text[:200]}"
            )
            raise DataSourceUnavailable(
                f"CoinGecko respondió {resp.status_code}. "
                f"Revisa COINGECKO_API_KEY en tu .env, o el rate limit."
            )

        raw = resp.json()
        if not raw:
            raise DataSourceUnavailable("CoinGecko devolvió una respuesta vacía.")

        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["volume"] = float("nan")  # el endpoint /ohlc no trae volumen — ver fetch_volume()
        df = df.sort_values("timestamp").reset_index(drop=True)
        self._last_status = SourceStatus(name="coingecko", connected=True,
                                          detail=f"{len(df)} velas", last_update=df["timestamp"].max())
        return df

    def fetch_volume(self, symbol: str, vs_currency: str = "usd", days: int = 365) -> pd.DataFrame:
        """Endpoint /coins/{id}/market_chart — trae precio+volumen (sin OHLC)."""
        coin_id = COIN_ID_MAP.get(symbol.upper(), symbol.lower())
        url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
        params = {"vs_currency": vs_currency, "days": days, "interval": "daily"}
        try:
            resp = requests.get(url, params=params, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as e:
            raise DataSourceUnavailable(f"CoinGecko volume request failed: {e}") from e
        if resp.status_code != 200:
            raise DataSourceUnavailable(f"CoinGecko volume respondió {resp.status_code}: {resp.text[:200]}")
        raw = resp.json()
        vols = raw.get("total_volumes", [])
        if not vols:
            raise DataSourceUnavailable("CoinGecko no devolvió volúmenes.")
        df = pd.DataFrame(vols, columns=["timestamp", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    def fetch_ohlcv(self, symbol: str, vs_currency: str, days: int) -> pd.DataFrame:
        """Combina OHLC + volumen (dos llamadas, misma fuente) en el
        esquema fijo que exige HistoricalPriceSource."""
        ohlc = self.fetch_ohlc(symbol, vs_currency, days)
        time.sleep(1.2)  # cortesía de rate-limit entre llamadas al tier gratuito
        vol = self.fetch_volume(symbol, vs_currency, days)

        ohlc = ohlc.sort_values("timestamp")
        vol = vol.sort_values("timestamp")
        merged = pd.merge_asof(ohlc.drop(columns=["volume"]), vol, on="timestamp",
                                direction="nearest", tolerance=pd.Timedelta("36h"))
        merged["volume"] = merged["volume"].fillna(method="ffill")
        return merged[["timestamp", "open", "high", "low", "close", "volume"]]

    def status(self) -> SourceStatus:
        return self._last_status

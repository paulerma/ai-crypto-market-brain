"""
DATA ENGINE — único punto de entrada a datos para todo lo que está
aguas abajo (features, modelos, decisión). Nada fuera de este archivo
debe importar un adaptador directamente.

Responsabilidades:
  - Pedir histórico real a CoinGeckoSource.
  - Cachear en disco (parquet) para no repetir llamadas ni gastar rate-limit.
  - Reportar el estado de cada fuente (para el panel "calidad de datos").
  - Registrar los adaptadores de Fase 2 aunque no estén implementados,
    para que el sistema sepa que existen y están "NO CONECTADOS" en
    vez de fingir que no existen.
"""

from pathlib import Path
import pandas as pd

from adapters.coingecko import CoinGeckoSource
from adapters.future_adapters import (
    BinanceLiveSource, DerivativesAdapter, OnChainAdapter, MacroAdapter,
)
from adapters.base import DataSourceUnavailable

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


class DataEngine:
    def __init__(self):
        self.historical = CoinGeckoSource()          # HISTÓRICO real (CoinGecko)
        self.live = BinanceLiveSource()               # Fase 2 — no conectado
        self.derivatives = DerivativesAdapter()        # Fase 2 — no conectado
        self.onchain = OnChainAdapter()                 # Fase 2 — no conectado
        self.macro = MacroAdapter()                     # Fase 2 — no conectado

    def get_ohlcv(self, symbol: str = "BTC", vs_currency: str = "usd",
                   days: int = 365, use_cache: bool = True) -> pd.DataFrame:
        cache_path = DATA_DIR / f"{symbol.lower()}_{vs_currency}_{days}d.parquet"
        if use_cache and cache_path.exists():
            return pd.read_parquet(cache_path)

        df = self.historical.fetch_ohlcv(symbol, vs_currency, days)
        df.to_parquet(cache_path, index=False)
        return df

    def data_quality_report(self) -> list[dict]:
        """Estado real de cada fuente — esto alimenta el panel
        'DATA STATUS' del dashboard. Nunca marca LIVE algo que no lo esté."""
        report = []
        try:
            st = self.historical.status()
            report.append({"source": "Histórico (CoinGecko)",
                            "connected": st.connected, "detail": st.detail})
        except Exception as e:
            report.append({"source": "Histórico (CoinGecko)",
                            "connected": False, "detail": str(e)})

        for label, adapter in [
            ("Exchange en vivo", self.live),
            ("Derivados", self.derivatives),
            ("On-chain", self.onchain),
            ("Macro", self.macro),
        ]:
            st = adapter.status()
            report.append({"source": label, "connected": st.connected, "detail": st.detail})
        return report

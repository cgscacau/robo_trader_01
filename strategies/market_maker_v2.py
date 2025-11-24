# strategies/market_maker_v2.py

from dataclasses import dataclass
from collections import deque
from typing import Optional, Dict, Any, List

from core.strategy import StrategyBase, Signal


@dataclass
class MarketMakerV2Config:
    """
    Market Maker adaptativo com base na volatilidade recente do mid-price.
    """
    min_spread: float = 1.0        # spread mínimo absoluto
    max_spread: float = 15.0       # spread máximo absoluto
    spread_pct: float = 0.0        # se > 0, usa % do mid como base
    quote_size: float = 0.001      # tamanho das ordens em cada lado
    tick_interval: int = 5         # gera quotes a cada N ticks

    vol_window: int = 50           # nº de mids usados p/ calcular volatilidade
    vol_factor: float = 1.0        # peso da volatilidade no spread


class MarketMakerV2(StrategyBase):
    """
    Market Maker v2:
    - A cada N ticks, calcula o mid price.
    - Estima volatilidade recente como desvio padrão dos mids.
    - Define spread alvo = base_spread + vol_factor * vol.
    - Aplica min_spread e max_spread.
    - Coloca bid e ask simétricos em torno do mid.

    Obs.:
    - Inventory e risco global são tratados fora (InventoryRiskManager e RiskManager).
    """

    def __init__(self, symbol: str, config: Optional[MarketMakerV2Config] = None):
        super().__init__(symbol)
        self.cfg = config or MarketMakerV2Config()
        self._counter = 0
        self._mid_history: deque[float] = deque(maxlen=self.cfg.vol_window)

    def _update_mid_history(self, mid: float) -> None:
        self._mid_history.append(mid)

    def _calc_volatility(self) -> float:
        """
        Volatilidade simples = desvio padrão dos mids salvos.
        Se não há dados suficientes, retorna 0.
        """
        n = len(self._mid_history)
        if n < 2:
            return 0.0

        mean = sum(self._mid_history) / n
        var = sum((x - mean) ** 2 for x in self._mid_history) / (n - 1)
        return var ** 0.5

    def on_tick(self, tick: Dict[str, Any]) -> List[Signal]:
        self._counter += 1

        bid = tick.get("bid")
        ask = tick.get("ask")

        if bid is None or ask is None:
            return []

        mid = (bid + ask) / 2.0
        self._update_mid_history(mid)

        if self._counter % self.cfg.tick_interval != 0:
            return []

        # Base spread
        if self.cfg.spread_pct > 0:
            base_spread = (self.cfg.spread_pct / 100.0) * mid
        else:
            base_spread = self.cfg.min_spread

        # Volatilidade recente dos mids
        vol = self._calc_volatility()

        # Spread adaptativo
        raw_spread = base_spread + self.cfg.vol_factor * vol
        desired_spread = max(self.cfg.min_spread, min(raw_spread, self.cfg.max_spread))

        quote_bid = mid - desired_spread / 2.0
        quote_ask = mid + desired_spread / 2.0

        signals: List[Signal] = [
            Signal(
                side="BUY",
                size=self.cfg.quote_size,
                order_type="LIMIT",
                price=quote_bid,
                tag="MM_V2_BID",
            ),
            Signal(
                side="SELL",
                size=self.cfg.quote_size,
                order_type="LIMIT",
                price=quote_ask,
                tag="MM_V2_ASK",
            ),
        ]
        return signals

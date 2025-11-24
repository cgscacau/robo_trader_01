# strategies/market_maker_v1.py

from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from core.strategy import StrategyBase, Signal


@dataclass
class MarketMakerV1Config:
    """
    Configuração básica do Market Maker v1.
    """
    min_spread: float = 1.0        # spread mínimo absoluto
    max_spread: float = 10.0       # spread máximo absoluto
    spread_pct: float = 0.0        # se > 0, usa % do mid em vez de min_spread
    quote_size: float = 0.001      # tamanho das ordens em cada lado
    tick_interval: int = 5         # gera quotes a cada N ticks


class MarketMakerV1(StrategyBase):
    """
    Market Maker v1:
    - A cada N ticks, calcula um mid price.
    - Define um spread alvo.
    - Coloca uma ordem de compra (bid) e uma ordem de venda (ask) simétricas em torno do mid.

    Observações:
    - Versão simplificada: não faz gestão de cancelamento, assume fill imediato
      (na prática teremos que evoluir para acompanhar ordens abertas).
    - Inventory risk é tratado externamente pelo InventoryRiskManager.
    """

    def __init__(self, symbol: str, config: Optional[MarketMakerV1Config] = None):
        super().__init__(symbol)
        self.cfg = config or MarketMakerV1Config()
        self._counter = 0

    def on_tick(self, tick: Dict[str, Any]) -> List[Signal]:
        self._counter += 1
        if self._counter % self.cfg.tick_interval != 0:
            return []

        bid = tick.get("bid")
        ask = tick.get("ask")

        if bid is None or ask is None:
            return []

        mid = (bid + ask) / 2.0

        # Define spread base
        if self.cfg.spread_pct > 0:
            base_spread = (self.cfg.spread_pct / 100.0) * mid
        else:
            base_spread = self.cfg.min_spread

        # Aplica limites
        desired_spread = max(self.cfg.min_spread, min(base_spread, self.cfg.max_spread))

        quote_bid = mid - desired_spread / 2.0
        quote_ask = mid + desired_spread / 2.0

        # Gera dois sinais: buy no bid, sell no ask
        signals: List[Signal] = [
            Signal(
                side="BUY",
                size=self.cfg.quote_size,
                order_type="LIMIT",
                price=quote_bid,
                tag="MM_BID",
            ),
            Signal(
                side="SELL",
                size=self.cfg.quote_size,
                order_type="LIMIT",
                price=quote_ask,
                tag="MM_ASK",
            ),
        ]
        return signals

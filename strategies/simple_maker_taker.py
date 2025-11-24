# strategies/simple_maker_taker.py

from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from core.strategy import StrategyBase, Signal, Side, OrderType


@dataclass
class SimpleMakerTakerConfig:
    min_spread: float = 1.0      # spread mínimo em unidades de preço
    order_size: float = 0.001    # quantidade de BTC (por exemplo)
    tick_interval: int = 5       # gera sinal a cada N ticks para não spammar


class SimpleMakerTakerStrategy(StrategyBase):
    """
    Estratégia simples para teste do fluxo:
    - A cada N ticks, verifica o spread bid/ask.
    - Se o spread >= min_spread, manda UMA ordem LIMIT alternando BUY/SELL.
    """

    def __init__(self, symbol: str, config: Optional[SimpleMakerTakerConfig] = None):
        super().__init__(symbol)
        self.cfg = config or SimpleMakerTakerConfig()
        self._counter = 0
        self._last_side: Side = "BUY"

    def on_tick(self, tick: Dict[str, Any]) -> List[Signal]:
        self._counter += 1
        if self._counter % self.cfg.tick_interval != 0:
            return []

        bid = tick.get("bid")
        ask = tick.get("ask")

        if bid is None or ask is None:
            return []

        spread = ask - bid
        if spread < self.cfg.min_spread:
            return []

        # alterna BUY/SELL só para simplificar
        self._last_side = "SELL" if self._last_side == "BUY" else "BUY"

        if self._last_side == "BUY":
            price = bid
        else:
            price = ask

        signal = Signal(
            side=self._last_side,
            size=self.cfg.order_size,
            order_type="LIMIT",
            price=price,
            tag="SIMPLE_MAKER_TAKER",
        )
        return [signal]

# strategies/imbalance_v1.py

from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Literal

from core.strategy import StrategyBase, Signal


SideBias = Literal["both", "long_only", "short_only"]


@dataclass
class ImbalanceV1Config:
    """
    Estratégia Imbalance V1:
    - Usa volume do melhor bid/ask (ou soma dos níveis, se alterarmos no futuro).
    - Calcula imbalance = (bid_size - ask_size) / (bid_size + ask_size).
    - Se |imbalance| >= threshold e total_size >= min_total_size:
        - imbalance > 0 -> pressão de compra (BUY)
        - imbalance < 0 -> pressão de venda (SELL)
    - Usa cooldown em ticks para evitar overtrading.
    - Respeita side_bias: both / long_only / short_only.
    """
    imbalance_threshold: float = 0.6   # valor entre 0 e 1
    min_total_size: float = 1.0        # bid_size + ask_size mínimo
    order_size: float = 0.001
    cooldown_ticks: int = 5
    side_bias: SideBias = "both"       # "both", "long_only", "short_only"


class ImbalanceV1(StrategyBase):
    def __init__(self, symbol: str, config: Optional[ImbalanceV1Config] = None):
        super().__init__(symbol)
        self.cfg = config or ImbalanceV1Config()
        self._cooldown_counter: int = 0

    def _bias_allows(self, side: str) -> bool:
        if self.cfg.side_bias == "both":
            return True
        if self.cfg.side_bias == "long_only" and side == "BUY":
            return True
        if self.cfg.side_bias == "short_only" and side == "SELL":
            return True
        return False

    def on_tick(self, tick: Dict[str, Any]) -> List[Signal]:
        # cooldown
        if self._cooldown_counter > 0:
            self._cooldown_counter -= 1
            return []

        bid = tick.get("bid")
        ask = tick.get("ask")
        bid_size = tick.get("bid_size")
        ask_size = tick.get("ask_size")

        # precisa de preço e volume
        if bid is None or ask is None or bid_size is None or ask_size is None:
            return []

        total_size = bid_size + ask_size
        if total_size <= 0 or total_size < self.cfg.min_total_size:
            return []

        imbalance = (bid_size - ask_size) / total_size

        # nada relevante
        if abs(imbalance) < self.cfg.imbalance_threshold:
            return []

        # decide lado
        if imbalance > 0:
            side = "BUY"
        else:
            side = "SELL"

        if not self._bias_allows(side):
            return []

        # ordem agressiva (MARKET) usando o last; o app usará tick["last"]
        signal = Signal(
            side=side,
            size=self.cfg.order_size,
            order_type="MARKET",
            price=None,
            tag="IMBALANCE_V1",
        )

        self._cooldown_counter = self.cfg.cooldown_ticks

        return [signal]

# strategies/mean_reversion_v1.py

from dataclasses import dataclass
from collections import deque
from typing import Optional, Dict, Any, List, Literal

from core.strategy import StrategyBase, Signal


SideBias = Literal["both", "long_only", "short_only"]


@dataclass
class MeanReversionV1Config:
    """
    Mean Reversion Microestrutural V1:
    - Observa últimos N preços "last".
    - Calcula média e desvio padrão.
    - Calcula z-score = (last - mean) / std.
    - Se z <= -z_threshold -> BUY (preço abaixo da média).
    - Se z >=  z_threshold -> SELL (preço acima da média).
    - Usa cooldown em ticks e side_bias.
    """
    lookback_ticks: int = 20
    z_threshold: float = 2.0
    order_size: float = 0.001
    cooldown_ticks: int = 10
    side_bias: SideBias = "both"   # "both", "long_only", "short_only"
    max_z_cap: float = 5.0         # limite absoluto para |z|


class MeanReversionV1(StrategyBase):
    def __init__(self, symbol: str, config: Optional[MeanReversionV1Config] = None):
        super().__init__(symbol)
        self.cfg = config or MeanReversionV1Config()
        self._prices: deque[float] = deque(maxlen=self.cfg.lookback_ticks)
        self._cooldown_counter: int = 0

    def _update_price_history(self, price: float) -> None:
        self._prices.append(price)

    def _bias_allows(self, side: str) -> bool:
        if self.cfg.side_bias == "both":
            return True
        if self.cfg.side_bias == "long_only" and side == "BUY":
            return True
        if self.cfg.side_bias == "short_only" and side == "SELL":
            return True
        return False

    def _enough_data(self) -> bool:
        return len(self._prices) >= self.cfg.lookback_ticks

    def _compute_z_score(self, last: float) -> Optional[float]:
        if not self._enough_data():
            return None

        prices = list(self._prices)
        n = len(prices)
        mean = sum(prices) / n

        # desvio padrão
        var = sum((p - mean) ** 2 for p in prices) / max(1, (n - 1))
        std = var ** 0.5

        if std <= 0:
            return None

        z = (last - mean) / std

        # limita z-score
        if z > self.cfg.max_z_cap:
            z = self.cfg.max_z_cap
        elif z < -self.cfg.max_z_cap:
            z = -self.cfg.max_z_cap

        return z

    def on_tick(self, tick: Dict[str, Any]) -> List[Signal]:
        last = tick.get("last")
        if last is None:
            return []

        self._update_price_history(last)

        # cooldown
        if self._cooldown_counter > 0:
            self._cooldown_counter -= 1
            return []

        z = self._compute_z_score(last)
        if z is None:
            return []

        # Sem gatilho
        if abs(z) < self.cfg.z_threshold:
            return []

        # z negativo: preço abaixo da média -> compra
        if z <= -self.cfg.z_threshold:
            side = "BUY"
        # z positivo: preço acima da média -> venda
        elif z >= self.cfg.z_threshold:
            side = "SELL"
        else:
            return []

        if not self._bias_allows(side):
            return []

        signal = Signal(
            side=side,
            size=self.cfg.order_size,
            order_type="MARKET",
            price=None,
            tag="MEAN_REV_V1",
        )

        self._cooldown_counter = self.cfg.cooldown_ticks

        return [signal]

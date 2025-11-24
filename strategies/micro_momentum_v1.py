# strategies/micro_momentum_v1.py

from dataclasses import dataclass
from collections import deque
from typing import Optional, Dict, Any, List, Literal

from core.strategy import StrategyBase, Signal


SideBias = Literal["both", "long_only", "short_only"]


@dataclass
class MicroMomentumV1Config:
    """
    Estratégia de Micro-Momentum:
    - Observa os últimos N ticks (lookback_ticks).
    - Verifica movimentos consecutivos de preço (min_moves).
    - Verifica retorno relativo mínimo (min_return).
    - Se tendência curta para cima/down for forte o suficiente,
      gera uma ordem MARKET na direção do movimento.
    - Usa cooldown em ticks para não operar em excesso.
    """
    lookback_ticks: int = 10
    min_moves: int = 3
    min_return: float = 0.0005   # ex.: 0.0005 = 0,05%
    order_size: float = 0.001
    cooldown_ticks: int = 10
    side_bias: SideBias = "both"  # "both", "long_only", "short_only"


class MicroMomentumV1(StrategyBase):
    def __init__(self, symbol: str, config: Optional[MicroMomentumV1Config] = None):
        super().__init__(symbol)
        self.cfg = config or MicroMomentumV1Config()
        self._last_prices: deque[float] = deque(maxlen=self.cfg.lookback_ticks)
        self._cooldown_counter: int = 0

    def _update_price_history(self, price: float) -> None:
        self._last_prices.append(price)

    def _enough_data(self) -> bool:
        return len(self._last_prices) >= self.cfg.lookback_ticks

    def _check_momentum(self) -> Optional[str]:
        """
        Retorna:
        - "UP"   se há micro-momentum de alta
        - "DOWN" se há micro-momentum de baixa
        - None   caso contrário
        """
        if not self._enough_data():
            return None

        prices = list(self._last_prices)
        p0 = prices[0]
        pN = prices[-1]

        if p0 <= 0:
            return None

        # retorno relativo total
        ret = (pN - p0) / p0

        # conta movimentos consecutivos
        up_moves = 0
        down_moves = 0
        for i in range(1, len(prices)):
            if prices[i] > prices[i - 1]:
                up_moves += 1
                down_moves = 0
            elif prices[i] < prices[i - 1]:
                down_moves += 1
                up_moves = 0
            else:
                # preço igual zera ambos
                up_moves = 0
                down_moves = 0

        # verifica tendência para cima
        if (
            up_moves >= self.cfg.min_moves
            and ret >= self.cfg.min_return
        ):
            return "UP"

        # verifica tendência para baixo
        if (
            down_moves >= self.cfg.min_moves
            and ret <= -self.cfg.min_return
        ):
            return "DOWN"

        return None

    def _bias_allows(self, direction: str) -> bool:
        """
        Verifica se o bias de lado permite operar na direção indicada.
        direction: "UP" ou "DOWN"
        """
        if self.cfg.side_bias == "both":
            return True
        if self.cfg.side_bias == "long_only" and direction == "UP":
            return True
        if self.cfg.side_bias == "short_only" and direction == "DOWN":
            return True
        return False

    def on_tick(self, tick: Dict[str, Any]) -> List[Signal]:
        last = tick.get("last")
        if last is None:
            return []

        # atualiza histórico de preços
        self._update_price_history(last)

        # cooldown em ticks
        if self._cooldown_counter > 0:
            self._cooldown_counter -= 1
            return []

        direction = self._check_momentum()
        if direction is None:
            return []

        if not self._bias_allows(direction):
            return []

        # Decide o lado da ordem
        if direction == "UP":
            side = "BUY"
        else:
            side = "SELL"

        # Ordem MARKET: price=None, app usa tick["last"]
        signal = Signal(
            side=side,
            size=self.cfg.order_size,
            order_type="MARKET",
            price=None,
            tag="MICRO_MOMENTUM_V1",
        )

        # reseta cooldown
        self._cooldown_counter = self.cfg.cooldown_ticks

        return [signal]

# core/strategy.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Optional, Dict, Any, List

Side = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT"]


@dataclass
class Signal:
    """
    Representa uma intenção de ordem da estratégia.
    """
    side: Side
    size: float                # quantidade (ex.: 0.001 BTC)
    order_type: OrderType = "LIMIT"
    price: Optional[float] = None  # obrigatório se LIMIT
    tag: Optional[str] = None      # identificador opcional (ex.: "MM_BID")
    

class StrategyBase(ABC):
    """
    Classe base para qualquer estratégia.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol

    @abstractmethod
    def on_tick(self, tick: Dict[str, Any]) -> List[Signal]:
        """
        Chamado a cada novo tick de mercado.

        Deve retornar:
          - []       -> nenhum trade neste tick
          - [Signal] -> uma ordem
          - [Signal, Signal, ...] -> múltiplas ordens (market making etc.)
        """
        ...

    def on_fill(self, fill: Dict[str, Any]) -> None:
        """
        Chamado quando uma ordem é executada (hook para estratégias mais avançadas).
        """
        pass

    def on_error(self, error: Exception) -> None:
        """
        Chamado quando ocorre algum erro relevante na execução.
        """
        pass

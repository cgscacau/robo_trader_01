# core/datafeed.py

import time
import random
from abc import ABC, abstractmethod
from typing import Dict, Iterator


class DataFeedBase(ABC):
    """
    Interface para qualquer fonte de dados de mercado.
    """

    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def ticks(self) -> Iterator[Dict]:
        """
        Deve gerar dicionários com pelo menos:
        {
            "symbol": str,
            "bid": float,
            "ask": float,
            "last": float,
            "ts": float,
        }
        """
        ...


class DummyDataFeed(DataFeedBase):
    """
    DataFeed de teste:
    - Gera preços com random walk ao redor de um preço inicial.
    - Útil para testar o fluxo sem conectar na exchange.
    """

    def __init__(self, symbol: str, start_price: float = 100000.0, tick_sleep: float = 0.5):
        self.symbol = symbol
        self.price = start_price
        self.tick_sleep = tick_sleep
        self._running = False

    def connect(self) -> None:
        self._running = True
        print(f"[DATAFEED] DummyDataFeed conectado para {self.symbol}")

    def disconnect(self) -> None:
        self._running = False
        print("[DATAFEED] DummyDataFeed desconectado")

    def ticks(self) -> Iterator[Dict]:
        self.connect()
        try:
            while self._running:
                # random walk simples
                delta = random.uniform(-5, 5)
                self.price = max(1, self.price + delta)

                spread = random.uniform(0.5, 2.0)
                bid = self.price - spread / 2
                ask = self.price + spread / 2
                last = self.price

                tick = {
                    "symbol": self.symbol,
                    "bid": bid,
                    "ask": ask,
                    "last": last,
                    "ts": time.time(),
                }

                yield tick
                time.sleep(self.tick_sleep)
        finally:
            self.disconnect()

# core/datafeed_binance.py

import time
from typing import Dict, Iterator

import requests

from core.datafeed import DataFeedBase


class BinanceDepthDataFeed(DataFeedBase):
    """
    Datafeed simples via REST /depth (order book top of book).
    Para HFT real, o ideal é WebSocket, mas isso já resolve para
    testes com o robô rodando em casa.
    """

    def __init__(
        self,
        symbol: str,
        base_url: str,
        tick_sleep: float = 0.5,
        limit: int = 5,
    ):
        self.symbol = symbol
        self.base_url = base_url
        self.tick_sleep = tick_sleep
        self.limit = limit
        self._running = False

    def connect(self) -> None:
        self._running = True
        print(f"[DATAFEED] BinanceDepthDataFeed conectado para {self.symbol}")

    def disconnect(self) -> None:
        self._running = False
        print("[DATAFEED] BinanceDepthDataFeed desconectado")

    def _fetch_depth(self) -> Dict:
        url = f"{self.base_url}/depth"
        params = {"symbol": self.symbol, "limit": self.limit}
        resp = requests.get(url, params=params, timeout=3)
        resp.raise_for_status()
        return resp.json()

    def ticks(self) -> Iterator[Dict]:
        self.connect()
        try:
            while self._running:
                depth = self._fetch_depth()
                bids = depth.get("bids", [])
                asks = depth.get("asks", [])

                if not bids or not asks:
                    time.sleep(self.tick_sleep)
                    continue

                best_bid_price = float(bids[0][0])
                best_ask_price = float(asks[0][0])
                last = (best_bid_price + best_ask_price) / 2.0

                tick = {
                    "symbol": self.symbol,
                    "bid": best_bid_price,
                    "ask": best_ask_price,
                    "last": last,
                    "ts": time.time(),
                }

                yield tick
                time.sleep(self.tick_sleep)

        finally:
            self.disconnect()

# core/datafeed_ws_binance.py

import json
import threading
import time
import queue
from typing import Dict, Iterator, Optional, List, Any

import websocket  # pacote websocket-client

from core.datafeed import DataFeedBase


class BinanceWebSocketDataFeed(DataFeedBase):
    """
    DataFeed via WebSocket da Binance (Spot ou Futures), usando stream de depth.
    - Conecta em um stream do tipo: btcusdt@depth5@100ms
    - Mantém top-of-book (melhor bid/ask) + volumes.
    """

    def __init__(
        self,
        symbol: str,
        market_type: str = "futures",
        levels: int = 5,
        speed: str = "100ms",
    ):
        self.symbol = symbol
        self.market_type = market_type
        self.levels = levels
        self.speed = speed

        sym_lower = symbol.lower()
        stream = f"{sym_lower}@depth{levels}@{speed}"

        if market_type == "spot":
            base_ws = "wss://stream.binance.com:9443/ws"
        else:
            # Futures USDT-M
            base_ws = "wss://fstream.binance.com/ws"

        self.ws_url = f"{base_ws}/{stream}"

        self._running = False
        self._ws_app: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=1000)

    # ----------------- Interface DataFeedBase ----------------- #

    def connect(self) -> None:
        if self._running:
            return

        self._running = True

        def on_message(ws, message: str):
            try:
                data = json.loads(message)
                bids: List[List[str]] = data.get("bids", [])
                asks: List[List[str]] = data.get("asks", [])

                if not bids or not asks:
                    return

                # cada item: [price, qty, ...]
                best_bid_price = float(bids[0][0])
                best_bid_size = float(bids[0][1])
                best_ask_price = float(asks[0][0])
                best_ask_size = float(asks[0][1])

                last = (best_bid_price + best_ask_price) / 2.0

                tick = {
                    "symbol": self.symbol,
                    "bid": best_bid_price,
                    "ask": best_ask_price,
                    "last": last,
                    "ts": time.time(),
                    # volumes no melhor nível
                    "bid_size": best_bid_size,
                    "ask_size": best_ask_size,
                    # opcional: níveis inteiros (preço, qty)
                    "bid_levels": [[float(p), float(q)] for p, q, *_ in bids],
                    "ask_levels": [[float(p), float(q)] for p, q, *_ in asks],
                }

                try:
                    self._queue.put_nowait(tick)
                except queue.Full:
                    # fila cheia: descarta o tick mais antigo
                    try:
                        self._queue.get_nowait()
                        self._queue.put_nowait(tick)
                    except queue.Empty:
                        pass
            except Exception as e:
                print(f"[WS] Erro ao processar mensagem: {e}")

        def on_error(ws, error):
            print(f"[WS] Erro no WebSocket: {error}")

        def on_close(ws, close_status_code, close_msg):
            print(f"[WS] Conexão WebSocket fechada: {close_status_code} {close_msg}")
            self._running = False

        def on_open(ws):
            print(f"[WS] Conectado ao stream {self.ws_url}")

        self._ws_app = websocket.WebSocketApp(
            self.ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        self._thread = threading.Thread(
            target=self._ws_app.run_forever, daemon=True
        )
        self._thread.start()
        print(f"[DATAFEED] BinanceWebSocketDataFeed conectado para {self.symbol}")

    def disconnect(self) -> None:
        self._running = False
        if self._ws_app is not None:
            try:
                self._ws_app.close()
            except Exception:
                pass
        print("[DATAFEED] BinanceWebSocketDataFeed desconectado")

    def ticks(self) -> Iterator[Dict]:
        """
        Iterator que consome ticks da fila interna.
        """
        self.connect()
        try:
            while self._running:
                try:
                    tick = self._queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                yield tick
        finally:
            self.disconnect()

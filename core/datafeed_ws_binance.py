# core/datafeed_ws_binance.py

import json
import time
import threading
import queue
from typing import Dict, Any, List, Tuple, Generator, Optional

try:
    import websocket  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Dependência ausente: 'websocket-client'. "
        "Adicione 'websocket-client' ao requirements.txt."
    ) from exc


class BinanceWebSocketDataFeed:
    """
    Datafeed via WebSocket na Binance (spot ou futures), usando streams de
    book de ofertas.

    - Usa o stream:   <symbol>@depth{levels}@{speed}
      Ex: btcusdt@depth10@100ms

    - Para simplificar, tratamos cada mensagem como um snapshot parcial do book,
      calculando:
        * best_bid, best_ask
        * last ≈ (best_bid + best_ask) / 2
        * bid_size / ask_size agregados (para imbalance)

    - Implementação com thread + queue para não bloquear o loop principal.
      Cada chamada a ticks() garante que o WebSocket está rodando e consome
      mensagens da fila.

    IMPORTANTE:
        Este é um datafeed público (não usa chave/segredo). O envio de ordens
        é controlado separadamente pelo ExecutionClient e RiskManager.
    """

    def __init__(
        self,
        symbol: str,
        market_type: str = "futures",  # "spot" ou "futures"
        levels: int = 5,
        speed: str = "100ms",
        ws_base_url_spot: Optional[str] = None,
        ws_base_url_futures: Optional[str] = None,
    ):
        self.symbol = symbol.lower()
        self.market_type = market_type.lower()
        self.depth_levels = int(levels)
        self.speed = speed

        # Endpoints padrão (podem ser sobrescritos via parâmetros/YAML)
        self.ws_base_url_spot = ws_base_url_spot or "wss://stream.binance.com:9443/ws"
        self.ws_base_url_futures = ws_base_url_futures or "wss://fstream.binance.com/ws"

        # Fila de ticks que serão consumidos pelo generator
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=1000)

        # Controle do WebSocket
        self._ws_app: Optional["websocket.WebSocketApp"] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._running = False

        # Estado do book (para fallback se alguma mensagem vier incompleta)
        self._last_bids: List[Tuple[float, float]] = []
        self._last_asks: List[Tuple[float, float]] = []
        self._last_mid: Optional[float] = None

    # ------------------------------------------------------------------ #
    # Interface pública
    # ------------------------------------------------------------------ #

    def ticks(self) -> Generator[Dict[str, Any], None, None]:
        """
        Generator infinito de ticks.

        Cada tick é um dicionário com:
            {
                "symbol": ...,
                "ts": ...,
                "last": ...,
                "bid": ...,
                "ask": ...,
                "bid_size": ...,
                "ask_size": ...,
                "bids": [(price, size), ...],
                "asks": [(price, size), ...],
            }
        """
        self._ensure_ws_running()

        while True:
            tick = self._queue.get()  # bloqueia até chegar dado
            yield tick

    # ------------------------------------------------------------------ #
    # WebSocket
    # ------------------------------------------------------------------ #

    def _ensure_ws_running(self) -> None:
        """
        Garante que o WebSocket está rodando em background.
        """
        if self._running:
            return

        self._running = True
        self._ws_thread = threading.Thread(
            target=self._run_ws_forever, name="BinanceWSFeed", daemon=True
        )
        self._ws_thread.start()

    def _build_stream_url(self) -> str:
        """
        Monta a URL do stream de depth da Binance.
        """
        stream_name = f"{self.symbol}@depth{self.depth_levels}@{self.speed}"

        if self.market_type == "spot":
            base = self.ws_base_url_spot.rstrip("/")
        else:
            # default: futures
            base = self.ws_base_url_futures.rstrip("/")

        return f"{base}/{stream_name}"

    def _run_ws_forever(self) -> None:
        """
        Loop principal do WebSocket. Em caso de erro, tenta reconectar
        com backoff simples.
        """
        backoff = 1.0
        while self._running:
            url = self._build_stream_url()

            def on_message(ws, message: str):
                self._handle_message(message)

            def on_error(ws, error):
                # Aqui não levantamos exceção pro app principal; apenas logar se quiser.
                # Para manter o exemplo simples, só marcamos que haverá nova tentativa.
                # Em produção, usar logging estruturado.
                # print(f"[BinanceWS] erro: {error}")
                pass

            def on_close(ws, close_status_code, close_msg):
                # print(f"[BinanceWS] fechado: {close_status_code} {close_msg}")
                pass

            def on_open(ws):
                # print(f"[BinanceWS] conectado em {url}")
                pass

            self._ws_app = websocket.WebSocketApp(
                url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                on_open=on_open,
            )

            try:
                # run_forever já faz ping/pong e reconexão básica
                self._ws_app.run_forever(
                    ping_interval=20,
                    ping_timeout=10,
                )
            except Exception:
                # Queda do run_forever -> espera e tenta de novo
                time.sleep(backoff)
                backoff = min(backoff * 2.0, 60.0)
                continue

            # Se chegou aqui e _running ainda é True, fazemos uma pausa
            time.sleep(backoff)
            backoff = min(backoff * 2.0, 60.0)

    # ------------------------------------------------------------------ #
    # Processamento de mensagens
    # ------------------------------------------------------------------ #

    def _handle_message(self, message: str) -> None:
        """
        Processa a mensagem de depth vinda da Binance e empilha um tick na fila.
        """
        try:
            raw = json.loads(message)
        except json.JSONDecodeError:
            return

        # Oracle do formato:
        # 1) Partial book depth (ex: @depth10@100ms):
        #    { "lastUpdateId": 12345,
        #      "bids": [["price","qty"], ...],
        #      "asks": [["price","qty"], ...] }
        #
        # 2) Diff. depth (depthUpdate):
        #    { "e": "depthUpdate", "E": 123456789, "s": "BNBBTC",
        #      "b": [...], "a": [...] }

        bids_raw = raw.get("bids") or raw.get("b") or []
        asks_raw = raw.get("asks") or raw.get("a") or []

        bids: List[Tuple[float, float]] = []
        asks: List[Tuple[float, float]] = []

        # Converte e limita número de níveis
        for p_str, q_str in bids_raw[: self.depth_levels]:
            price = float(p_str)
            qty = float(q_str)
            if qty > 0.0:
                bids.append((price, qty))

        for p_str, q_str in asks_raw[: self.depth_levels]:
            price = float(p_str)
            qty = float(q_str)
            if qty > 0.0:
                asks.append((price, qty))

        if not bids and not asks:
            # Nada útil
            return

        # Mantém estado para fallback se faltar de um dos lados
        if bids:
            self._last_bids = bids
        if asks:
            self._last_asks = asks

        if not bids:
            bids = self._last_bids
        if not asks:
            asks = self._last_asks

        if not bids or not asks:
            # ainda assim sem book completo
            return

        best_bid, _ = bids[0]
        best_ask, _ = asks[0]

        mid = (best_bid + best_ask) / 2.0
        self._last_mid = mid

        # event time se existir; senão, time.time()
        event_ts_ms = raw.get("E")
        if isinstance(event_ts_ms, (int, float)):
            ts = float(event_ts_ms) / 1000.0
        else:
            ts = time.time()

        # definimos last ≈ mid (é suficiente para o laboratório de MM/imbalance)
        last = mid

        total_bid_size = sum(size for _, size in bids)
        total_ask_size = sum(size for _, size in asks)

        tick = {
            "symbol": self.symbol.upper(),
            "ts": ts,
            "last": last,
            "bid": best_bid,
            "ask": best_ask,
            "bid_size": total_bid_size,
            "ask_size": total_ask_size,
            "bids": bids,
            "asks": asks,
        }

        # Empilha na fila, descartando o mais antigo se estiver cheia
        try:
            self._queue.put_nowait(tick)
        except queue.Full:
            try:
                _ = self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(tick)
            except queue.Full:
                # Se ainda assim estiver cheia, ignoramos este tick
                pass

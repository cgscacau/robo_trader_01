# core/datafeed_dummy_orderbook.py

import time
import math
import random
from typing import Dict, Any, Generator, List, Tuple, Optional


class UltraDummyOrderBookFeed:
    """
    Datafeed dummy avançado que simula um order book com microestrutura:

    - Preço médio (mid) em random walk.
    - Spread variável.
    - Eventos de fluxo de ordens:
        * agressive_buy  -> last em ask, mid tende a subir
        * agressive_sell -> last em bid, mid tende a cair
        * noise          -> last perto do mid
    - Book com múltiplos níveis.
    - Liquidez variável e assimétrica (para imbalance).

    É ideal para:
        - testar estratégias de market making (simple_maker_taker, MMv1, MMv2),
        - testar estratégias de imbalance,
        - fazer laboratório de HFT sem conectar em corretora real.
    """

    def __init__(
        self,
        symbol: str,
        start_price: float = 100_000.0,
        tick_sleep: float = 0.0,
        volatility: float = 0.0005,
        base_spread_ticks: float = 1.0,
        depth_levels: int = 5,
        base_liquidity: float = 1.0,
        seed: Optional[int] = None,
    ):
        """
        Args:
            symbol: símbolo negociado (ex: "BTCUSDT").
            start_price: preço inicial (mid).
            tick_sleep: tempo de sleep entre ticks (em segundos). Use 0 em backtest.
            volatility: volatilidade base da caminhada aleatória (em % do preço).
            base_spread_ticks: spread médio em ticks (multiplicador do 'tick_size').
            depth_levels: número de níveis em cada lado do book.
            base_liquidity: tamanho médio das ordens em cada nível.
            seed: semente opcional para reprodutibilidade.
        """
        self.symbol = symbol
        self.mid_price = float(start_price)
        self.tick_sleep = float(tick_sleep)
        self.volatility = float(volatility)
        self.base_spread_ticks = float(base_spread_ticks)
        self.depth_levels = int(depth_levels)
        self.base_liquidity = float(base_liquidity)

        # definimos um "tick_size" sintético relativo ao preço
        self.tick_size = self.mid_price * 0.0001  # 1 bp como tamanho de tick base

        # random state
        self._rng = random.Random(seed)

        # contador de ticks (só para referência interna)
        self._tick_counter = 0

    # ------------------------------------------------------------------ #
    # API principal
    # ------------------------------------------------------------------ #

    def ticks(self) -> Generator[Dict[str, Any], None, None]:
        """
        Gera ticks infinitos com estrutura de book e trades sintéticos.

        Cada yield retorna um dicionário com:
            - symbol
            - ts (epoch seconds)
            - last
            - bid, ask
            - bid_size, ask_size (agregado do book)
            - bids: [(price, size), ...]
            - asks: [(price, size), ...]
        """
        while True:
            self._tick_counter += 1

            # 1) Simula alguns eventos de microestrutura antes de "observar" o book
            self._simulate_micro_events()

            # 2) A partir do mid+spread, constrói o book
            bids, asks = self._build_order_book()

            best_bid, best_bid_size = bids[0]
            best_ask, best_ask_size = asks[0]

            # 3) Decide o último preço negociado (last) neste tick
            last = self._sample_last_trade(best_bid, best_ask)

            ts = time.time()

            # 4) Agrega tamanho total de cada lado (para estratégias de imbalance)
            total_bid_size = sum(size for _, size in bids)
            total_ask_size = sum(size for _, size in asks)

            tick = {
                "symbol": self.symbol,
                "ts": ts,
                "last": last,
                "bid": best_bid,
                "ask": best_ask,
                "bid_size": total_bid_size,
                "ask_size": total_ask_size,
                "bids": bids,
                "asks": asks,
            }

            yield tick

            if self.tick_sleep > 0:
                time.sleep(self.tick_sleep)

    # ------------------------------------------------------------------ #
    # Microestrutura
    # ------------------------------------------------------------------ #

    def _simulate_micro_events(self) -> None:
        """
        Simula alguns micro eventos entre um tick e outro:

        - Caminhada aleatória no mid com viés pequeno, dependendo do último "humor".
        - Eventos de agressão (buy/sell) que deslocam levemente o mid.
        """
        # número de eventos entre um tick e outro
        n_events = self._rng.randint(1, 5)

        for _ in range(n_events):
            event_type = self._sample_event_type()

            # variação percentual base (pequena)
            base_move = self.volatility * self._rng.uniform(0.2, 1.0)

            if event_type == "aggressive_buy":
                # compra agressiva puxa o mid pra cima
                self.mid_price *= (1.0 + base_move)
            elif event_type == "aggressive_sell":
                # venda agressiva empurra o mid pra baixo
                self.mid_price *= (1.0 - base_move)
            else:
                # noise: flutuação pequena ao redor
                direction = 1.0 if self._rng.random() < 0.5 else -1.0
                self.mid_price *= (1.0 + direction * base_move * 0.3)

        # evita mid_price ir para valores inválidos
        self.mid_price = max(self.mid_price, self.tick_size * 10.0)

    def _sample_event_type(self) -> str:
        """
        Define qual tipo de evento acontece.
        Dá um peso maior para 'noise', mas inclui agressões suficientes
        para gerar tendência de curto prazo.
        """
        r = self._rng.random()
        if r < 0.15:
            return "aggressive_buy"
        elif r < 0.30:
            return "aggressive_sell"
        else:
            return "noise"

    # ------------------------------------------------------------------ #
    # Construção do order book
    # ------------------------------------------------------------------ #

    def _build_order_book(self) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
        """
        Constrói o book sintético (bids, asks) com diversos níveis.

        - spread médio baseado em base_spread_ticks * tick_size
        - spread varia com ruído
        - liquidez decai à medida que se afasta do top-of-book
        - leve assimetria aleatória entre bid e ask
        """
        # espalha o spread em torno de um valor base, com ruído
        base_spread = self.base_spread_ticks * self.tick_size

        # ruído multiplicativo entre ~0.5x e 2x
        spread_noise = self._rng.uniform(0.5, 2.0)
        spread = max(base_spread * spread_noise, self.tick_size * 0.5)

        best_bid = self.mid_price - spread / 2.0
        best_ask = self.mid_price + spread / 2.0

        bids: List[Tuple[float, float]] = []
        asks: List[Tuple[float, float]] = []

        # fator de decaimento da liquidez por nível
        decay = self._rng.uniform(0.6, 0.9)

        for level in range(self.depth_levels):
            # distância em ticks do melhor preço
            dist_ticks = level + 1

            # preços por nível
            bid_price = best_bid - dist_ticks * self.tick_size
            ask_price = best_ask + dist_ticks * self.tick_size

            # liquidez base
            # adiciona assimetria aleatória entre bid e ask
            bid_liq = self.base_liquidity * (decay ** level) * self._rng.uniform(0.8, 1.2)
            ask_liq = self.base_liquidity * (decay ** level) * self._rng.uniform(0.8, 1.2)

            bids.append((bid_price, bid_liq))
            asks.append((ask_price, ask_liq))

        # garante que o primeiro nível (top-of-book) seja exatamente best_bid/best_ask
        # e com um pouco mais de liquidez
        top_bid_liq = self.base_liquidity * self._rng.uniform(1.0, 2.0)
        top_ask_liq = self.base_liquidity * self._rng.uniform(1.0, 2.0)

        bids.insert(0, (best_bid, top_bid_liq))
        asks.insert(0, (best_ask, top_ask_liq))

        return bids, asks

    # ------------------------------------------------------------------ #
    # Geração do último preço (last)
    # ------------------------------------------------------------------ #

    def _sample_last_trade(self, best_bid: float, best_ask: float) -> float:
        """
        Define o último preço negociado (last) neste tick.

        - Em buys agressivos -> tende a negociar no ask ou acima.
        - Em sells agressivos -> tende a negociar no bid ou abaixo.
        - Em noise -> em torno do mid, dentro do spread.
        """
        mid = (best_bid + best_ask) / 2.0
        spread = max(best_ask - best_bid, self.tick_size * 0.5)

        # escolhe tipo de trade para este tick
        trade_type = self._sample_event_type()

        if trade_type == "aggressive_buy":
            # trade em ask ou levemente acima
            last = best_ask * (1.0 + self._rng.uniform(0.0, 0.0002))
        elif trade_type == "aggressive_sell":
            # trade em bid ou levemente abaixo
            last = best_bid * (1.0 - self._rng.uniform(0.0, 0.0002))
        else:
            # trade dentro do spread, perto do mid
            offset = (self._rng.random() - 0.5) * spread * 0.8
            last = mid + offset

        # segurança: nunca deixa last <= 0
        return max(last, self.tick_size * 10.0)

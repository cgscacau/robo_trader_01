# core/position.py

from dataclasses import dataclass


@dataclass
class PositionState:
    """
    Snapshot do estado da posição.
    """
    qty: float
    avg_price: float
    realized_pnl: float


class PositionManager:
    """
    Gerencia posição e PnL de um único símbolo linear (ex: BTCUSDT).
    - qty > 0  => posição comprada (long)
    - qty < 0  => posição vendida (short)
    - qty = 0  => zerado

    Regras básicas:
    - Mesma direção (ex: long e compra mais): recalcula preço médio.
    - Direção oposta (ex: long e vende): fecha parte ou toda a posição.
        - Se fechar totalmente e ainda sobrar quantidade, abre posição inversa.
    """

    def __init__(self):
        self._qty = 0.0
        self._avg_price = 0.0
        self._realized_pnl = 0.0

    # ----------------- Propriedades ----------------- #

    @property
    def qty(self) -> float:
        return self._qty

    @property
    def avg_price(self) -> float:
        return self._avg_price

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    # ----------------- Métodos principais ----------------- #

    def on_trade(self, side: str, qty: float, price: float) -> None:
        """
        Registra uma execução de trade.

        side: "BUY" ou "SELL"
        qty:  quantidade positiva (ex: 0.001 BTC)
        price: preço de execução
        """
        if qty <= 0:
            raise ValueError("qty deve ser positiva em on_trade().")

        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("side deve ser 'BUY' ou 'SELL'.")

        if self._qty == 0:
            # Sem posição: abre nova
            self._open_new_position(side, qty, price)
        else:
            # Já existe posição
            current_dir = 1 if self._qty > 0 else -1
            trade_dir = 1 if side == "BUY" else -1

            if current_dir == trade_dir:
                # Mesma direção: aumenta posição e ajusta preço médio
                self._add_to_position(qty, price, trade_dir)
            else:
                # Direção oposta: fecha parcial ou total, podendo reverter
                self._close_or_reverse(qty, price, trade_dir)

    def unrealized_pnl(self, current_price: float) -> float:
        """
        PnL não realizado com base no preço atual.
        """
        if self._qty == 0:
            return 0.0

        direction = 1 if self._qty > 0 else -1
        abs_qty = abs(self._qty)
        return (current_price - self._avg_price) * abs_qty * direction

    def snapshot(self) -> PositionState:
        """
        Retorna um snapshot imutável do estado da posição.
        """
        return PositionState(
            qty=self._qty,
            avg_price=self._avg_price,
            realized_pnl=self._realized_pnl,
        )

    # ----------------- Internos ----------------- #

    def _open_new_position(self, side: str, qty: float, price: float) -> None:
        direction = 1 if side == "BUY" else -1
        self._qty = direction * qty
        self._avg_price = price

    def _add_to_position(self, qty: float, price: float, direction: int) -> None:
        """
        Aumenta posição na mesma direção, ajustando o preço médio.
        """
        old_abs_qty = abs(self._qty)
        new_abs_qty = old_abs_qty + qty

        # preço médio ponderado
        self._avg_price = (
            (self._avg_price * old_abs_qty) + (price * qty)
        ) / new_abs_qty

        self._qty = direction * new_abs_qty

    def _close_or_reverse(self, qty: float, price: float, trade_dir: int) -> None:
        """
        Fecha parcial/totalmente a posição existente.
        Se a quantidade do trade for maior que a posição, reverte.
        """
        current_dir = 1 if self._qty > 0 else -1
        abs_pos = abs(self._qty)
        trade_qty = qty

        # Quantidade que vai efetivamente fechar a posição atual
        close_qty = min(abs_pos, trade_qty)

        # PnL da parte fechada
        pnl = (price - self._avg_price) * close_qty * current_dir
        self._realized_pnl += pnl

        if trade_qty == abs_pos:
            # Fecha completamente e fica zerado
            self._qty = 0.0
            self._avg_price = 0.0
            return

        if trade_qty < abs_pos:
            # Fecha parcial: sobra posição na direção original
            remaining = abs_pos - trade_qty
            self._qty = current_dir * remaining
            # Preço médio da parte restante continua o mesmo
            return

        # trade_qty > abs_pos -> fecha tudo e abre posição na direção oposta
        new_qty = trade_qty - abs_pos
        new_dir = trade_dir  # direção do novo trade
        self._qty = new_dir * new_qty
        self._avg_price = price

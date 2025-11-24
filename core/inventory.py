# core/inventory.py

from dataclasses import dataclass


@dataclass(frozen=True)
class InventoryLimits:
    """
    Limites de inventário para um único símbolo.
    - max_abs_qty: limite em quantidade absoluta (ex: 0.02 BTC).
    - max_notional_pct: limite em % do equity da conta para a posição líquida.
    """
    max_abs_qty: float
    max_notional_pct: float


class InventoryLimitExceeded(Exception):
    """Exceção lançada quando o limite de inventário é violado."""
    pass


class InventoryRiskManager:
    """
    Responsável por limitar o inventário (posição líquida) do robô.
    Não controla PnL nem número de trades, somente exposição em quantidade e notional.
    """

    def __init__(self, limits: InventoryLimits):
        self.limits = limits

    def validate_inventory(
        self,
        current_qty: float,
        trade_side: str,
        trade_qty: float,
        price: float,
        account_equity: float,
    ) -> None:
        """
        Verifica se, após aplicar o trade, a posição hipotética continua dentro dos limites.
        - current_qty: posição atual (positiva long, negativa short).
        - trade_side: "BUY" ou "SELL".
        - trade_qty: quantidade positiva (ex: 0.001).
        - price: preço do trade (fill ou estimado).
        - account_equity: equity atual da conta em USDT (ou moeda base).

        Se violar limite, levanta InventoryLimitExceeded.
        """
        if trade_qty <= 0:
            raise ValueError("trade_qty deve ser positiva em validate_inventory().")

        trade_side = trade_side.upper()
        if trade_side not in ("BUY", "SELL"):
            raise ValueError("trade_side deve ser 'BUY' ou 'SELL'.")

        if account_equity <= 0:
            raise ValueError("Equity da conta inválido para validação de inventário.")

        trade_dir = 1 if trade_side == "BUY" else -1

        # Posição hipotética após o trade
        new_qty = current_qty + trade_dir * trade_qty
        abs_new_qty = abs(new_qty)

        # 1) Limite em quantidade absoluta
        if abs_new_qty > self.limits.max_abs_qty:
            raise InventoryLimitExceeded(
                f"Limite de inventário em quantidade violado: "
                f"|{abs_new_qty:.6f}| > {self.limits.max_abs_qty:.6f}"
            )

        # 2) Limite em notional (% do equity)
        notional = abs_new_qty * price
        pct_equity = (notional / account_equity) * 100.0

        if pct_equity > self.limits.max_notional_pct:
            raise InventoryLimitExceeded(
                f"Limite de inventário em notional violado: "
                f"{pct_equity:.2f}% > {self.limits.max_notional_pct:.2f}% do equity."
            )

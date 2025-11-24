# core/risk.py

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RiskLimits:
    """Limites estáticos de risco – NÃO mudam durante o dia."""
    max_daily_loss_pct: float
    max_daily_loss_value: float
    max_position_size_pct: float
    max_open_trades: int
    circuit_breaker_enabled: bool = True


class CircuitBreakerTripped(Exception):
    """Exceção lançada quando o circuito de proteção é disparado."""
    pass


class RiskManager:
    """
    Responsável por:
    - Controlar perdas diárias
    - Limitar tamanho de posição
    - Limitar número de trades abertos
    - Disparar circuit breaker quando necessário
    """

    def __init__(self, limits: RiskLimits):
        self.limits = limits
        self._daily_pnl = 0.0
        self._open_trades = 0
        self._circuit_breaker_hit = False

    # --------- Atualizações de estado --------- #

    def register_trade_pnl(self, pnl: float) -> None:
        """
        Atualiza o PnL diário após o fechamento de uma operação.
        pnl > 0 ganho, pnl < 0 perda.
        """
        if self._circuit_breaker_hit:
            return

        self._daily_pnl += pnl
        self._check_daily_loss()

    def increment_open_trades(self) -> None:
        if self._circuit_breaker_hit:
            raise CircuitBreakerTripped("Circuit breaker ativo – não abrir novas posições.")
        self._open_trades += 1
        if self._open_trades > self.limits.max_open_trades:
            raise CircuitBreakerTripped(
                f"Número máximo de operações abertas excedido: {self._open_trades}"
            )

    def decrement_open_trades(self) -> None:
        self._open_trades = max(0, self._open_trades - 1)

    # --------- Checks de risco --------- #

    def validate_position_size(
        self, account_equity: float, position_notional: float
    ) -> None:
        """
        Verifica se o tamanho da posição respeita o limite em % do saldo.
        """
        if self._circuit_breaker_hit:
            raise CircuitBreakerTripped("Circuit breaker ativo – não abrir novas posições.")

        if account_equity <= 0:
            raise ValueError("Equity da conta inválido para cálculo de risco.")

        pct = (position_notional / account_equity) * 100.0

        if pct > self.limits.max_position_size_pct:
            raise CircuitBreakerTripped(
                f"Posição ({pct:.2f}%) excede o limite de "
                f"{self.limits.max_position_size_pct:.2f}% do saldo."
            )

    def _check_daily_loss(self) -> None:
        """
        Checa se a perda diária atingiu algum limite.
        """
        if not self.limits.circuit_breaker_enabled:
            return

        if self._daily_pnl >= 0:
            return  # ainda no lucro

        loss_abs = abs(self._daily_pnl)
        # Em um app mais completo, você teria equity atual para calcular perda %.

        if loss_abs >= self.limits.max_daily_loss_value:
            self._trigger_circuit_breaker(
                f"Perda diária absoluta atingiu {loss_abs:.2f}, "
                f"limite: {self.limits.max_daily_loss_value:.2f}"
            )

    def _trigger_circuit_breaker(self, reason: str) -> None:
        self._circuit_breaker_hit = True
        raise CircuitBreakerTripped(f"Circuit breaker disparado: {reason}")

    # --------- Getters --------- #

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def open_trades(self) -> int:
        return self._open_trades

    @property
    def circuit_breaker_hit(self) -> bool:
        return self._circuit_breaker_hit

# tests/test_risk.py

import pytest

from core.risk import RiskLimits, RiskManager, CircuitBreakerTripped


def make_default_risk_manager() -> RiskManager:
    limits = RiskLimits(
        max_daily_loss_pct=2.0,
        max_daily_loss_value=50.0,
        max_position_size_pct=10.0,
        max_open_trades=3,
        circuit_breaker_enabled=True,
    )
    return RiskManager(limits)


def test_position_size_above_limit_triggers_circuit_breaker():
    risk = make_default_risk_manager()
    equity = 1000.0

    # 200 USDT de posição => 20% do equity (acima do limite de 10%)
    with pytest.raises(CircuitBreakerTripped):
        risk.validate_position_size(account_equity=equity, position_notional=200.0)


def test_daily_loss_above_absolute_limit_triggers_circuit_breaker():
    risk = make_default_risk_manager()

    # registra uma perda de 60 USDT (maior que max_daily_loss_value = 50)
    with pytest.raises(CircuitBreakerTripped):
        risk.register_trade_pnl(-60.0)


def test_open_trades_above_limit_triggers_circuit_breaker():
    risk = make_default_risk_manager()

    # limite de 3 operações abertas
    risk.increment_open_trades()
    risk.increment_open_trades()
    risk.increment_open_trades()

    with pytest.raises(CircuitBreakerTripped):
        risk.increment_open_trades()

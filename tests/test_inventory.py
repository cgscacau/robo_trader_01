# tests/test_inventory.py

import pytest

from core.inventory import InventoryLimits, InventoryRiskManager, InventoryLimitExceeded


def make_default_inventory_manager() -> InventoryRiskManager:
    limits = InventoryLimits(
        max_abs_qty=0.02,
        max_notional_pct=30.0,
    )
    return InventoryRiskManager(limits)


def test_inventory_limit_abs_qty_exceeded():
    inv = make_default_inventory_manager()
    equity = 1000.0
    price = 100000.0

    # posição atual: 0.015 BTC
    current_qty = 0.015
    # trade: BUY 0.01 => nova posição = 0.025 (maior que 0.02)
    with pytest.raises(InventoryLimitExceeded):
        inv.validate_inventory(
            current_qty=current_qty,
            trade_side="BUY",
            trade_qty=0.01,
            price=price,
            account_equity=equity,
        )


def test_inventory_limit_notional_pct_exceeded():
    inv = make_default_inventory_manager()

    equity = 1000.0
    price = 100000.0
    current_qty = 0.0

    # BUY 0.01 BTC @ 100k => notional = 1000 => 100% do equity
    # limite está em 30%
    with pytest.raises(InventoryLimitExceeded):
        inv.validate_inventory(
            current_qty=current_qty,
            trade_side="BUY",
            trade_qty=0.01,
            price=price,
            account_equity=equity,
        )


def test_inventory_within_limits_passes():
    inv = make_default_inventory_manager()

    equity = 1000.0
    price = 50000.0
    current_qty = 0.0

    # BUY 0.01 BTC @ 50k => notional = 500 => 50% do equity
    # max_notional_pct = 30% -> em tese deveria falhar
    # vamos ajustar os limites só pra esse teste
    inv_ok = InventoryRiskManager(
        InventoryLimits(max_abs_qty=0.05, max_notional_pct=60.0)
    )

    # não deve levantar exceção
    inv_ok.validate_inventory(
        current_qty=current_qty,
        trade_side="BUY",
        trade_qty=0.01,
        price=price,
        account_equity=equity,
    )

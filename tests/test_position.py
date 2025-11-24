# tests/test_position.py

from core.position import PositionManager


def test_open_long_and_scale_up():
    pos = PositionManager()

    # Abre long 1 @ 100
    pos.on_trade(side="BUY", qty=1.0, price=100.0)
    assert pos.qty == 1.0
    assert pos.avg_price == 100.0
    assert pos.realized_pnl == 0.0

    # Compra mais 1 @ 110 => qty=2, avg=105
    pos.on_trade(side="BUY", qty=1.0, price=110.0)
    assert pos.qty == 2.0
    assert pos.avg_price == 105.0
    assert pos.realized_pnl == 0.0


def test_close_long_full():
    pos = PositionManager()

    pos.on_trade("BUY", 2.0, 100.0)   # long 2 @ 100
    pos.on_trade("SELL", 2.0, 120.0)  # fecha tudo @ 120

    assert pos.qty == 0.0
    assert pos.avg_price == 0.0
    # PnL = (120 - 100) * 2
    assert pos.realized_pnl == 40.0


def test_close_long_partial():
    pos = PositionManager()

    pos.on_trade("BUY", 2.0, 100.0)   # long 2 @ 100
    pos.on_trade("SELL", 1.0, 110.0)  # vende 1 @ 110

    # Sobrou 1 contrato long @ 100
    assert pos.qty == 1.0
    assert pos.avg_price == 100.0
    # PnL = (110 - 100) * 1
    assert pos.realized_pnl == 10.0


def test_flip_long_to_short():
    pos = PositionManager()

    pos.on_trade("BUY", 1.0, 100.0)   # long 1 @ 100
    pos.on_trade("SELL", 2.0, 90.0)   # vende 2 @ 90

    # Fecha long de 1: PnL = (90 - 100)*1*1 = -10
    # Sobra short 1 @ 90
    assert pos.realized_pnl == -10.0
    assert pos.qty == -1.0
    assert pos.avg_price == 90.0


def test_open_and_close_short():
    pos = PositionManager()

    pos.on_trade("SELL", 1.0, 100.0)  # short 1 @ 100
    pos.on_trade("BUY", 1.0, 90.0)    # recompra @ 90

    # PnL short = (90 - 100) * 1 * (-1) = 10
    assert pos.qty == 0.0
    assert pos.avg_price == 0.0
    assert pos.realized_pnl == 10.0


def test_unrealized_pnl_long_and_short():
    pos = PositionManager()

    # Long 1 @ 100, preço atual 110 => +10
    pos.on_trade("BUY", 1.0, 100.0)
    assert pos.unrealized_pnl(110.0) == 10.0

    # Reverte: vende 2 @ 120 -> realized e fica short 1 @ 120
    pos.on_trade("SELL", 2.0, 120.0)
    # Posição atual: -1 @ 120
    # Preço atual 110 => PnL não realizado = (110 - 120)*1*(-1) = 10
    assert pos.qty == -1.0
    assert pos.unrealized_pnl(110.0) == 10.0

# tests/test_micro_momentum_v1.py

from strategies.micro_momentum_v1 import MicroMomentumV1, MicroMomentumV1Config


def test_micro_momentum_buy_signal():
    cfg = MicroMomentumV1Config(
        lookback_ticks=5,
        min_moves=2,
        min_return=0.0001,
        order_size=0.001,
        cooldown_ticks=3,
        side_bias="both",
    )
    strat = MicroMomentumV1(symbol="BTCUSDT", config=cfg)

    prices = [100.0, 100.1, 100.2, 100.3, 100.4]

    signals = []
    for p in prices:
        tick = {"symbol": "BTCUSDT", "bid": p, "ask": p, "last": p, "ts": 0.0}
        signals = strat.on_tick(tick)

    assert len(signals) == 1
    assert signals[0].side == "BUY"
    assert signals[0].order_type == "MARKET"

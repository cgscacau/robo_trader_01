# tests/test_mean_reversion_v1.py

from strategies.mean_reversion_v1 import MeanReversionV1, MeanReversionV1Config


def test_mean_reversion_generates_signal():
    cfg = MeanReversionV1Config(
        lookback_ticks=5,
        z_threshold=1.0,
        order_size=0.001,
        cooldown_ticks=3,
        side_bias="both",
        max_z_cap=5.0,
    )
    strat = MeanReversionV1(symbol="BTCUSDT", config=cfg)

    # preços: 100, 100, 100, 100, 102 -> último bem acima da média
    prices = [100.0, 100.0, 100.0, 100.0, 102.0]

    signals = []
    for p in prices:
        tick = {"symbol": "BTCUSDT", "bid": p, "ask": p, "last": p, "ts": 0.0}
        signals = strat.on_tick(tick)

    assert len(signals) == 1
    assert signals[0].side == "SELL"
    assert signals[0].order_type == "MARKET"

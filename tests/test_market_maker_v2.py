# tests/test_market_maker_v2.py

from strategies.market_maker_v2 import MarketMakerV2, MarketMakerV2Config


def test_market_maker_v2_generates_two_quotes():
    cfg = MarketMakerV2Config(
        min_spread=1.0,
        max_spread=10.0,
        spread_pct=0.0,
        quote_size=0.001,
        tick_interval=1,
        vol_window=10,
        vol_factor=1.0,
    )
    strat = MarketMakerV2(symbol="BTCUSDT", config=cfg)

    # Alimenta alguns mids pra criar volatilidade
    prices = [
        {"bid": 100.0, "ask": 102.0},
        {"bid": 101.0, "ask": 103.0},
        {"bid": 99.0, "ask": 101.0},
    ]

    signals = []
    for p in prices:
        tick = {
            "symbol": "BTCUSDT",
            "bid": p["bid"],
            "ask": p["ask"],
            "last": (p["bid"] + p["ask"]) / 2.0,
            "ts": 0.0,
        }
        signals = strat.on_tick(tick)

    assert len(signals) == 2
    sides = {s.side for s in signals}
    assert sides == {"BUY", "SELL"}

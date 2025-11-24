# tests/test_market_maker_v1.py

from strategies.market_maker_v1 import MarketMakerV1, MarketMakerV1Config


def test_market_maker_generates_two_quotes():
    cfg = MarketMakerV1Config(
        min_spread=1.0,
        max_spread=5.0,
        spread_pct=0.0,
        quote_size=0.001,
        tick_interval=1,
    )
    strat = MarketMakerV1(symbol="BTCUSDT", config=cfg)

    tick = {
        "symbol": "BTCUSDT",
        "bid": 100.0,
        "ask": 102.0,
        "last": 101.0,
        "ts": 0.0,
    }

    signals = strat.on_tick(tick)
    assert len(signals) == 2
    sides = {s.side for s in signals}
    assert sides == {"BUY", "SELL"}

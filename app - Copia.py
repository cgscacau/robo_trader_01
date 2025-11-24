# app.py

import yaml
import logging

from core.risk import RiskLimits, RiskManager, CircuitBreakerTripped
from core.execution import ExecutionClient   # mock genérico
from core.datafeed import DummyDataFeed
from core.datafeed_binance import BinanceDepthDataFeed
from core.datafeed_ws_binance import BinanceWebSocketDataFeed
from core.execution_binance import BinanceExecutionClient
from core.position import PositionManager
from core.inventory import InventoryLimits, InventoryRiskManager, InventoryLimitExceeded
from core.logging_utils import setup_logging

from strategies.simple_maker_taker import (
    SimpleMakerTakerStrategy,
    SimpleMakerTakerConfig,
)
from strategies.market_maker_v1 import (
    MarketMakerV1,
    MarketMakerV1Config,
)
from strategies.market_maker_v2 import (
    MarketMakerV2,
    MarketMakerV2Config,
)
from strategies.micro_momentum_v1 import (
    MicroMomentumV1,
    MicroMomentumV1Config,
)
from strategies.imbalance_v1 import (
    ImbalanceV1,
    ImbalanceV1Config,
)
from strategies.mean_reversion_v1 import (
    MeanReversionV1,
    MeanReversionV1Config,
)


def load_settings(path: str = "config/settings_example.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_risk_manager(risk_cfg: dict) -> RiskManager:
    limits = RiskLimits(
        max_daily_loss_pct=risk_cfg["max_daily_loss_pct"],
        max_daily_loss_value=risk_cfg["max_daily_loss_value"],
        max_position_size_pct=risk_cfg["max_position_size_pct"],
        max_open_trades=risk_cfg["max_open_trades"],
        circuit_breaker_enabled=risk_cfg["circuit_breaker"]["enabled"],
    )
    return RiskManager(limits)


def build_inventory_manager(risk_cfg: dict) -> InventoryRiskManager:
    inv_cfg = risk_cfg.get("inventory", {})
    limits = InventoryLimits(
        max_abs_qty=inv_cfg.get("max_abs_qty", 0.02),
        max_notional_pct=inv_cfg.get("max_notional_pct", 30.0),
    )
    return InventoryRiskManager(limits)


def build_datafeed(exchange_cfg: dict):
    provider = exchange_cfg.get("provider", "dummy")
    datafeed_type = exchange_cfg.get("datafeed", "dummy")
    symbol = exchange_cfg["symbol"]

    if provider == "dummy" or datafeed_type == "dummy":
        return DummyDataFeed(symbol=symbol, start_price=100000.0, tick_sleep=0.5)

    if provider == "binance":
        market_type = exchange_cfg.get("market_type", "futures")

        if datafeed_type == "rest":
            if market_type == "spot":
                base_url = "https://api.binance.com/api/v3"
            else:
                base_url = "https://fapi.binance.com/fapi/v1"

            return BinanceDepthDataFeed(
                symbol=symbol,
                base_url=base_url,
                tick_sleep=0.5,
                limit=5,
            )

        elif datafeed_type == "ws":
            return BinanceWebSocketDataFeed(
                symbol=symbol,
                market_type=market_type,
                levels=5,
                speed="100ms",
            )

        else:
            raise ValueError(f"Tipo de datafeed desconhecido: {datafeed_type}")

    raise ValueError(f"Provider de exchange desconhecido: {provider}")


def build_execution_client(exchange_cfg: dict, trading_cfg: dict):
    provider = exchange_cfg.get("provider", "dummy")
    dry_run = trading_cfg.get("dry_run", True)

    if provider == "dummy":
        # Cliente mock já é, na prática, dry-run
        return ExecutionClient(
            base_url=exchange_cfg.get("base_url_spot", ""),
            api_key=exchange_cfg.get("api_key", ""),
            api_secret=exchange_cfg.get("api_secret", ""),
            testnet=True,
        )

    elif provider == "binance":
        return BinanceExecutionClient(
            api_key=exchange_cfg["api_key"],
            api_secret=exchange_cfg["api_secret"],
            market_type=exchange_cfg.get("market_type", "futures"),
            testnet=exchange_cfg.get("testnet", True),
            recv_window=exchange_cfg.get("recv_window", 5000),
            dry_run=dry_run,
        )

    else:
        raise ValueError(f"Provider de exchange desconhecido: {provider}")


def build_strategy(symbol: str, strategy_cfg: dict):
    name = strategy_cfg.get("name", "simple_maker_taker")
    params = strategy_cfg.get("params", {})

    if name == "simple_maker_taker":
        cfg = SimpleMakerTakerConfig(
            min_spread=params.get("min_spread", 1.0),
            order_size=params.get("order_size", 0.001),
            tick_interval=params.get("tick_interval", 5),
        )
        return SimpleMakerTakerStrategy(symbol=symbol, config=cfg)

    elif name == "market_maker_v1":
        cfg = MarketMakerV1Config(
            min_spread=params.get("min_spread", 1.0),
            max_spread=params.get("max_spread", 10.0),
            spread_pct=params.get("spread_pct", 0.0),
            quote_size=params.get("quote_size", 0.001),
            tick_interval=params.get("tick_interval", 5),
        )
        return MarketMakerV1(symbol=symbol, config=cfg)

    elif name == "market_maker_v2":
        cfg = MarketMakerV2Config(
            min_spread=params.get("min_spread", 1.0),
            max_spread=params.get("max_spread", 15.0),
            spread_pct=params.get("spread_pct", 0.0),
            quote_size=params.get("quote_size", 0.001),
            tick_interval=params.get("tick_interval", 5),
            vol_window=params.get("vol_window", 50),
            vol_factor=params.get("vol_factor", 1.0),
        )
        return MarketMakerV2(symbol=symbol, config=cfg)

    elif name == "micro_momentum_v1":
        cfg = MicroMomentumV1Config(
            lookback_ticks=params.get("lookback_ticks", 10),
            min_moves=params.get("min_moves", 3),
            min_return=params.get("min_return", 0.0005),
            order_size=params.get("order_size", 0.001),
            cooldown_ticks=params.get("cooldown_ticks", 10),
            side_bias=params.get("side_bias", "both"),
        )
        return MicroMomentumV1(symbol=symbol, config=cfg)

    elif name == "imbalance_v1":
        cfg = ImbalanceV1Config(
            imbalance_threshold=params.get("imbalance_threshold", 0.6),
            min_total_size=params.get("min_total_size", 1.0),
            order_size=params.get("imbalance_order_size", 0.001),
            cooldown_ticks=params.get("imbalance_cooldown_ticks", 5),
            side_bias=params.get("imbalance_side_bias", "both"),
        )
        return ImbalanceV1(symbol=symbol, config=cfg)

    elif name == "mean_reversion_v1":
        cfg = MeanReversionV1Config(
            lookback_ticks=params.get("mr_lookback_ticks", 20),
            z_threshold=params.get("mr_z_threshold", 2.0),
            order_size=params.get("mr_order_size", 0.001),
            cooldown_ticks=params.get("mr_cooldown_ticks", 10),
            side_bias=params.get("mr_side_bias", "both"),
            max_z_cap=params.get("mr_max_z_cap", 5.0),
        )
        return MeanReversionV1(symbol=symbol, config=cfg)

    else:
        raise ValueError(f"Estratégia desconhecida: {name}")


def main():
    # --------- Carrega config --------- #
    settings = load_settings()
    exchange_cfg = settings["exchange"]
    risk_cfg = settings["risk"]
    strat_cfg = settings.get("strategy", {})
    logging_cfg = settings.get("logging", {})
    trading_cfg = settings.get("trading", {})

    # --------- Logging estruturado --------- #
    setup_logging(
        level=logging_cfg.get("level", "INFO"),
        json_logs=logging_cfg.get("json", True),
        filename=logging_cfg.get("file"),
    )
    logger = logging.getLogger("hft_bot")

    symbol = exchange_cfg["symbol"]
    provider = exchange_cfg.get("provider", "dummy")
    datafeed_type = exchange_cfg.get("datafeed", "dummy")
    strategy_name = strat_cfg.get("name", "simple_maker_taker")
    dry_run = trading_cfg.get("dry_run", True)

    logger.info(
        "Inicializando bot.",
        extra={
            "symbol": symbol,
            "provider": provider,
            "datafeed": datafeed_type,
            "strategy": strategy_name,
            "dry_run": dry_run,
        },
    )

    # 1) Riscos
    risk = build_risk_manager(risk_cfg)
    inv_risk = build_inventory_manager(risk_cfg)

    # 2) Execução
    exec_client = build_execution_client(exchange_cfg, trading_cfg)

    # 3) Estratégia
    strategy = build_strategy(symbol, strat_cfg)

    # 4) Datafeed
    datafeed = build_datafeed(exchange_cfg)

    # 5) Posição
    pos_manager = PositionManager()

    try:
        for tick in datafeed.ticks():
            signals = strategy.on_tick(tick)

            if not signals:
                continue

            for signal in signals:
                try:
                    fill_price = signal.price if signal.price is not None else tick["last"]
                    equity = exec_client.get_account_equity()

                    # --------- INVENTORY RISK --------- #
                    inv_risk.validate_inventory(
                        current_qty=pos_manager.qty,
                        trade_side=signal.side,
                        trade_qty=signal.size,
                        price=fill_price,
                        account_equity=equity,
                    )

                    # --------- RISCO POR POSIÇÃO / CIRCUIT BREAKER --------- #
                    notional = signal.size * fill_price
                    risk.validate_position_size(
                        account_equity=equity,
                        position_notional=notional,
                    )
                    risk.increment_open_trades()

                    # --------- EXECUÇÃO --------- #
                    order_res = exec_client.send_order(symbol, signal)

                    # --------- POSIÇÃO E PnL --------- #
                    realized_before = pos_manager.realized_pnl
                    pos_manager.on_trade(
                        side=signal.side,
                        qty=signal.size,
                        price=fill_price,
                    )
                    realized_after = pos_manager.realized_pnl
                    trade_pnl = realized_after - realized_before

                    # Atualiza PnL no Risk Manager
                    risk.register_trade_pnl(trade_pnl)
                    risk.decrement_open_trades()

                    snap = pos_manager.snapshot()

                    logger.info(
                        "Trade executado.",
                        extra={
                            "signal_tag": signal.tag,
                            "side": signal.side,
                            "size": signal.size,
                            "price": fill_price,
                            "order_response": order_res,
                            "position_qty": snap.qty,
                            "position_avg_price": snap.avg_price,
                            "realized_pnl": snap.realized_pnl,
                            "trade_pnl": trade_pnl,
                        },
                    )

                except InventoryLimitExceeded as inv_err:
                    logger.warning(
                        "Trade rejeitado por limite de inventário.",
                        extra={
                            "signal_tag": signal.tag,
                            "side": signal.side,
                            "size": signal.size,
                            "error": str(inv_err),
                        },
                    )
                    continue

                except CircuitBreakerTripped as cb:
                    logger.error(
                        "Circuit breaker disparado. Encerrando o bot.",
                        extra={"error": str(cb)},
                    )
                    return

    except KeyboardInterrupt:
        logger.info("Bot interrompido pelo usuário.")


if __name__ == "__main__":
    main()

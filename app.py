# app.py

import os
import yaml
import logging
from typing import Dict, Any

from core.risk import RiskLimits, RiskManager
from core.execution import ExecutionClient
from core.datafeed import DummyDataFeed
from core.datafeed_binance import BinanceDepthDataFeed
from core.datafeed_ws_binance import BinanceWebSocketDataFeed
from core.execution_binance import BinanceExecutionClient
from core.position import PositionManager
from core.inventory import InventoryLimits, InventoryRiskManager
from core.logging_utils import setup_logging
from core.engine import TradingEngine, EngineEvent
from core.datafeed_dummy_orderbook import UltraDummyOrderBookFeed

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


# ------------------------------------------------------------------ #
# Mapeamento de ambientes -> arquivos de config
# ------------------------------------------------------------------ #

CONFIG_MAP: Dict[str, str] = {
    "lab_dummy": "config/settings_lab_dummy.yaml",
    "binance_testnet": "config/settings_binance_testnet.yaml",
    "binance_live": "config/settings_binance_live.yaml",
}


def _apply_env_hardening(settings: Dict[str, Any], env_name: str) -> Dict[str, Any]:
    """
    Regras extras de segurança dependendo do ambiente.
    - Em qualquer ambiente, trading.dry_run default = True.
    - Em binance_live:
        * circuit_breaker sempre habilitado
        * dry_run só pode ser False se variáveis de ambiente permitirem.
    """
    risk = settings.setdefault("risk", {})
    trading = settings.setdefault("trading", {})

    # Nunca assumimos dry_run=False sem ser explícito
    trading.setdefault("dry_run", True)

    if env_name == "binance_live":
        cb = risk.setdefault("circuit_breaker", {})
        cb["enabled"] = True  # imutável em live

        allow_real = os.getenv("ALLOW_REAL_TRADING", "false").lower() == "true"
        confirm = os.getenv("CONFIRM_I_UNDERSTAND_RISK", "no").lower() == "yes"

        if not (allow_real and confirm):
            trading["dry_run"] = True

    return settings


def load_settings(path: str | None = None) -> Dict[str, Any]:
    """
    Carrega o YAML de configuração.

    - Se `path` for fornecido, usa esse caminho relativo ao diretório do app.
    - Caso contrário, escolhe o arquivo com base em APP_ENV:
        * lab_dummy
        * binance_testnet
        * binance_live

    Usa caminho ABSOLUTO baseado no diretório do app.py,
    para não depender do diretório corrente do processo.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))

    if path is None:
        env_name = os.getenv("APP_ENV", "lab_dummy")
        cfg_rel_path = CONFIG_MAP.get(env_name, CONFIG_MAP["lab_dummy"])
    else:
        env_name = os.getenv("APP_ENV", "lab_dummy")
        cfg_rel_path = path

    cfg_path = os.path.join(base_dir, cfg_rel_path)

    if not os.path.exists(cfg_path):
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    settings["env"] = env_name
    settings = _apply_env_hardening(settings, env_name)
    return settings



# ------------------------------------------------------------------ #
# Builders de componentes
# ------------------------------------------------------------------ #

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
    """
    Fabrica o datafeed de acordo com provider + tipo definidos no YAML.
    """
    provider = exchange_cfg.get("provider", "dummy")
    datafeed_type = exchange_cfg.get("datafeed", "dummy")
    symbol = exchange_cfg["symbol"]

    # ----------- PROVIDER DUMMY ----------- #
    if provider == "dummy":
        if datafeed_type in ("dummy", "dummy_trades"):
            return DummyDataFeed(
                symbol=symbol,
                start_price=exchange_cfg.get("start_price", 100000.0),
                tick_sleep=exchange_cfg.get("tick_sleep", 0.0),
            )

        elif datafeed_type == "dummy_orderbook":
            return UltraDummyOrderBookFeed(
                symbol=symbol,
                start_price=exchange_cfg.get("start_price", 100000.0),
                tick_sleep=exchange_cfg.get("tick_sleep", 0.0),
                volatility=exchange_cfg.get("volatility", 0.0005),
                base_spread_ticks=exchange_cfg.get("base_spread_ticks", 1.0),
                depth_levels=exchange_cfg.get("depth_levels", 5),
                base_liquidity=exchange_cfg.get("base_liquidity", 1.0),
                seed=exchange_cfg.get("seed"),
            )

        else:
            raise ValueError(f"Tipo de datafeed dummy desconhecido: {datafeed_type}")

    # ----------- PROVIDER BINANCE ----------- #
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
                tick_sleep=exchange_cfg.get("tick_sleep", 0.5),
                limit=exchange_cfg.get("depth_limit", 5),
            )

        elif datafeed_type == "ws":
            return BinanceWebSocketDataFeed(
                symbol=symbol,
                market_type=market_type,
                levels=exchange_cfg.get("depth_levels", 5),
                speed=exchange_cfg.get("ws_speed", "100ms"),
                ws_base_url_spot=exchange_cfg.get("ws_base_url_spot"),
                ws_base_url_futures=exchange_cfg.get("ws_base_url_futures"),
            )

        else:
            raise ValueError(f"Tipo de datafeed binance desconhecido: {datafeed_type}")

    raise ValueError(f"Provider de exchange desconhecido: {provider}")


def build_execution_client(exchange_cfg: dict, trading_cfg: dict):
    provider = exchange_cfg.get("provider", "dummy")
    dry_run = trading_cfg.get("dry_run", True)

    if provider == "dummy":
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


# ------------------------------------------------------------------ #
# CLI principal (modo linha de comando, separado do Streamlit)
# ------------------------------------------------------------------ #

def main():
    settings = load_settings()

    exchange_cfg = settings["exchange"]
    risk_cfg = settings["risk"]
    strat_cfg = settings.get("strategy", {})
    logging_cfg = settings.get("logging", {})
    trading_cfg = settings.get("trading", {})
    env_name = settings.get("env", "lab_dummy")

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
            "env": env_name,
            "symbol": symbol,
            "provider": provider,
            "datafeed": datafeed_type,
            "strategy": strategy_name,
            "dry_run": dry_run,
        },
    )

    risk = build_risk_manager(risk_cfg)
    inv_risk = build_inventory_manager(risk_cfg)
    exec_client = build_execution_client(exchange_cfg, trading_cfg)
    strategy = build_strategy(symbol, strat_cfg)
    datafeed = build_datafeed(exchange_cfg)
    pos_manager = PositionManager()

    engine = TradingEngine(
        symbol=symbol,
        strategy=strategy,
        risk_manager=risk,
        inventory_manager=inv_risk,
        execution_client=exec_client,
        position_manager=pos_manager,
        logger=logger,
        raise_on_circuit_breaker=False,
    )

    try:
        for tick in datafeed.ticks():
            events = engine.process_tick(tick)

            for ev in events:
                if ev.type == "trade_executed":
                    logger.info("Trade executado.", extra=ev.data)
                elif ev.type == "signal_rejected":
                    logger.warning("Sinal rejeitado.", extra=ev.data)
                elif ev.type == "circuit_breaker":
                    logger.error(
                        "Circuit breaker disparado, encerrando loop.", extra=ev.data
                    )
                    return
                elif ev.type == "error":
                    logger.error("Erro na engine.", extra=ev.data)

            if not engine.running:
                logger.warning("Engine em estado 'stopped'. Encerrando bot.")
                break

    except KeyboardInterrupt:
        logger.info("Bot interrompido pelo usuário.")


if __name__ == "__main__":
    main()


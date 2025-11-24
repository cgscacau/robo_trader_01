# backtest_runner.py

import csv
from typing import List, Dict, Any

from app import (
    load_settings,
    build_strategy,
    build_risk_manager,
    build_inventory_manager,
)
from core.backtest import BacktestConfig, BacktestEngine


def load_ticks_from_csv(data_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Carrega ticks de um CSV conforme definição em data_cfg.
    Espera colunas:
      - time_column
      - bid_column
      - ask_column
      - last_column
      - (opcional) bid_size_column
      - (opcional) ask_size_column
    """
    path = data_cfg["csv_path"]
    time_col = data_cfg.get("time_column", "timestamp")
    bid_col = data_cfg.get("bid_column", "bid")
    ask_col = data_cfg.get("ask_column", "ask")
    last_col = data_cfg.get("last_column", "last")
    bid_size_col = data_cfg.get("bid_size_column", "bid_size")
    ask_size_col = data_cfg.get("ask_size_column", "ask_size")

    ticks: List[Dict[str, Any]] = []

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = float(row[time_col])
                bid = float(row[bid_col]) if row.get(bid_col) not in (None, "") else None
                ask = float(row[ask_col]) if row.get(ask_col) not in (None, "") else None
                last_val = row.get(last_col)

                if last_val is None or last_val == "":
                    # se não tiver last, usar média de bid/ask se ambos existirem
                    if bid is not None and ask is not None:
                        last = (bid + ask) / 2.0
                    else:
                        continue
                else:
                    last = float(last_val)

                bid_size = None
                ask_size = None

                if bid_size_col in row and row[bid_size_col] not in (None, ""):
                    bid_size = float(row[bid_size_col])
                if ask_size_col in row and row[ask_size_col] not in (None, ""):
                    ask_size = float(row[ask_size_col])

                tick = {
                    "symbol": data_cfg.get("symbol", "UNKNOWN"),
                    "bid": bid,
                    "ask": ask,
                    "last": last,
                    "ts": ts,
                    "bid_size": bid_size,
                    "ask_size": ask_size,
                }
                ticks.append(tick)
            except Exception:
                # pula linha inválida
                continue

    return ticks


def main():
    # Carrega settings (mesmo YAML do app)
    settings = load_settings("config/settings_example.yaml")

    exchange_cfg = settings["exchange"]
    risk_cfg = settings["risk"]
    strat_cfg = settings["strategy"]
    data_cfg = settings.get("data", {})
    backtest_cfg = settings.get("backtest", {})

    symbol = exchange_cfg["symbol"]

    # Constrói componentes (reutilizando funções do app.py)
    strategy = build_strategy(symbol, strat_cfg)
    risk_manager = build_risk_manager(risk_cfg)
    inventory_manager = build_inventory_manager(risk_cfg)

    bt_conf = BacktestConfig(
        initial_equity=backtest_cfg.get("initial_equity", 1000.0),
        fee_rate=backtest_cfg.get("fee_rate", 0.0004),
        slippage_bps=backtest_cfg.get("slippage_bps", 0.0),
    )

    # Carrega histórico de ticks
    ticks = load_ticks_from_csv(data_cfg)

    engine = BacktestEngine(
        symbol=symbol,
        strategy=strategy,
        risk_manager=risk_manager,
        inventory_manager=inventory_manager,
        config=bt_conf,
    )

    result = engine.run(ticks)

    # Imprime resumo
    summary = result.summary
    print("===== RESUMO DO BACKTEST =====")
    print(f"Equity inicial : {summary['initial_equity']:.2f}")
    print(f"Equity final   : {summary['final_equity']:.2f}")
    print(f"PnL líquido    : {summary['net_pnl']:.2f}")
    print(f"Trades         : {summary['total_trades']}")
    print(f"Wins           : {summary['wins']}")
    print(f"Losses         : {summary['losses']}")
    print(f"Win rate       : {summary['win_rate_pct']:.2f}%")
    print(f"Max drawdown   : {summary['max_drawdown']:.2f}")


if __name__ == "__main__":
    main()

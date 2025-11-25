# streamlit_app.py

from typing import List, Dict, Any

import streamlit as st
import pandas as pd

from app import (
    load_settings,
    build_strategy,
    build_risk_manager,
    build_inventory_manager,
    build_datafeed,
    build_execution_client,
)
from core.engine import TradingEngine, EngineEvent
from core.position import PositionManager


# ========================= Helpers de inicialização ========================= #

def init_engine_and_data(
    strategy_cfg: Dict[str, Any],
    exchange_override: Dict[str, Any] | None = None,
):
    """
    Inicializa engine, datafeed e históricos na sessão do Streamlit,
    usando:
      - strategy_cfg vindo da UI
      - exchange_cfg = YAML + override vindo da UI (para provider dummy)

    Esse método SEMPRE lê o settings pelo load_settings(), o que garante
    que o ambiente (lab_dummy / binance_testnet / binance_live) seja respeitado.
    """
    settings = load_settings()

    base_exchange_cfg = settings["exchange"]
    risk_cfg = settings["risk"]
    trading_cfg = settings.get("trading", {})

    # Aplica override de exchange se existir (somente em memória do app)
    if exchange_override:
        exchange_cfg = {**base_exchange_cfg, **exchange_override}
    else:
        exchange_cfg = base_exchange_cfg

    symbol = exchange_cfg["symbol"]

    # Constrói componentes core
    strategy = build_strategy(symbol, strategy_cfg)
    risk_manager = build_risk_manager(risk_cfg)
    inventory_manager = build_inventory_manager(risk_cfg)
    execution_client = build_execution_client(exchange_cfg, trading_cfg)
    pos_manager = PositionManager()

    engine = TradingEngine(
        symbol=symbol,
        strategy=strategy,
        risk_manager=risk_manager,
        inventory_manager=inventory_manager,
        execution_client=execution_client,
        position_manager=pos_manager,
        logger=None,
        raise_on_circuit_breaker=False,
    )

    datafeed = build_datafeed(exchange_cfg)
    data_iter = datafeed.ticks()

    # Guarda no estado da sessão
    st.session_state.engine = engine
    st.session_state.data_iter = data_iter

    # históricos p/ gráficos
    st.session_state.price_history: List[Dict[str, float]] = []
    st.session_state.pnl_history: List[Dict[str, float]] = []
    st.session_state.trades: List[Dict[str, Any]] = []
    st.session_state.event_log: List[Dict[str, Any]] = []

    # equity fictícia para lab (1000 + realized_pnl)
    st.session_state.initial_equity = 1000.0

    # guarda a exchange_cfg efetiva (pós override) para mostrar na UI
    st.session_state.exchange_effective_cfg = exchange_cfg


def process_n_ticks(n: int):
    """
    Processa N ticks usando o engine e atualiza
    histórico de preço, PnL, trades e log de eventos.
    """
    engine: TradingEngine = st.session_state.engine
    data_iter = st.session_state.data_iter

    for _ in range(n):
        try:
            tick = next(data_iter)
        except StopIteration:
            st.warning("Datafeed chegou ao fim (StopIteration).")
            break

        events: List[EngineEvent] = engine.process_tick(tick)
        snap = engine.snapshot()

        ts = float(tick.get("ts", 0.0))
        last_price = float(tick.get("last", 0.0))

        # Se o feed fornecer bid/ask/tamanhos, usamos; senão, caímos para last/0
        bid = float(tick.get("bid", last_price))
        ask = float(tick.get("ask", last_price))
        bid_size = float(tick.get("bid_size", 0.0))
        ask_size = float(tick.get("ask_size", 0.0))

        # Histórico de preço + book agregado
        st.session_state.price_history.append(
            {
                "ts": ts,
                "last": last_price,
                "bid": bid,
                "ask": ask,
                "bid_size": bid_size,
                "ask_size": ask_size,
            }
        )

        # PnL realizado do snapshot de posição
        realized_pnl = float(snap["position"]["realized_pnl"])
        equity = st.session_state.initial_equity + realized_pnl

        st.session_state.pnl_history.append(
            {"ts": ts, "realized_pnl": realized_pnl, "equity": equity}
        )

        # Eventos
        for ev in events:
            if ev.type == "trade_executed":
                st.session_state.trades.append(ev.data)
                st.session_state.event_log.append(
                    {
                        "ts": ts,
                        "type": "trade_executed",
                        "msg": f"{ev.data['side']} {ev.data['size']} @ {ev.data['price']}",
                        "tag": ev.data.get("signal_tag"),
                    }
                )
            elif ev.type == "signal_rejected":
                st.session_state.event_log.append(
                    {
                        "ts": ts,
                        "type": "signal_rejected",
                        "msg": ev.data.get("reason", "") + " – " + ev.data.get("error", ""),
                        "tag": ev.data.get("signal_tag"),
                    }
                )
            elif ev.type == "circuit_breaker":
                st.session_state.event_log.append(
                    {
                        "ts": ts,
                        "type": "circuit_breaker",
                        "msg": ev.data.get("message", ""),
                        "tag": None,
                    }
                )
                st.warning(f"Circuit breaker disparado: {ev.data.get('message')}")
                return
            elif ev.type == "error":
                st.session_state.event_log.append(
                    {
                        "ts": ts,
                        "type": "error",
                        "msg": ev.data.get("message", ""),
                        "tag": ev.data.get("signal_tag"),
                    }
                )
                st.error(f"Erro na engine: {ev.data.get('message')}")


def compute_metrics() -> Dict[str, float]:
    """
    Calcula métricas básicas a partir dos trades e da curva de PnL.
    """
    trades = st.session_state.trades
    pnl_hist = st.session_state.pnl_history

    total_trades = len(trades)
    if total_trades == 0:
        return {
            "net_pnl": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "total_trades": 0,
        }

    pnls = [float(t.get("trade_pnl", 0.0)) for t in trades]
    wins = sum(1 for x in pnls if x > 0)
    win_rate = (wins / total_trades) * 100.0 if total_trades > 0 else 0.0
    net_pnl = sum(pnls)

    max_dd = 0.0
    if pnl_hist:
        eq_series = [row["equity"] for row in pnl_hist]
        max_eq = eq_series[0]
        for eq in eq_series:
            if eq > max_eq:
                max_eq = eq
            dd = max_eq - eq
            if dd > max_dd:
                max_dd = dd

    return {
        "net_pnl": net_pnl,
        "win_rate": win_rate,
        "max_drawdown": max_dd,
        "total_trades": total_trades,
    }


# ========================= UI principal ========================= #

def main():
    st.set_page_config(page_title="Robô HFT - Lab Streamlit", layout="wide")

    # 1) Carrega YAML + identifica ambiente
    settings = load_settings()
    env_name = settings.get("env", "lab_dummy")

    base_exchange_cfg = settings["exchange"]
    yaml_strat_cfg = settings["strategy"]
    yaml_strat_params = yaml_strat_cfg.get("params", {})

    provider = base_exchange_cfg.get("provider", "dummy")

    # 2) Título + banner de ambiente
    st.title("🤖 Robô HFT – Laboratório em Streamlit")

    if env_name == "lab_dummy":
        st.caption("Ambiente atual: **LAB / Dummy** (simulação completa).")
    elif env_name == "binance_testnet":
        st.caption(
            "Ambiente atual: **Binance Testnet** – dados reais, ordens em conta de teste "
            "(por padrão em `dry_run`)."
        )
    elif env_name == "binance_live":
        st.error(
            "⚠ Ambiente atual: **Binance LIVE** – use SOMENTE após todos os testes.\n"
            "Ordens reais SÓ são enviadas se variáveis de ambiente obrigatórias estiverem habilitadas."
        )
    else:
        st.caption(f"Ambiente atual: **{env_name}**")

    st.markdown("---")

    # 3) Estratégia em sessão (para manter ao trocar widgets)
    if "strategy_cfg" not in st.session_state:
        st.session_state.strategy_cfg = {
            "name": yaml_strat_cfg.get("name", "simple_maker_taker"),
            "params": dict(yaml_strat_params),
        }

    # 4) Exchange override (apenas para provider dummy; em Binance é ignorado)
    if "exchange_override" not in st.session_state:
        st.session_state.exchange_override = {}

    # ------------------------------------------------------------------ #
    # Sidebar: estratégia e parâmetros
    # ------------------------------------------------------------------ #

    st.sidebar.header("Configuração da Estratégia")

    strategy_options = [
        "simple_maker_taker",
        "market_maker_v1",
        "market_maker_v2",
        "micro_momentum_v1",
        "imbalance_v1",
        "mean_reversion_v1",
    ]

    current_strategy_cfg = st.session_state.strategy_cfg
    current_name = current_strategy_cfg.get("name", yaml_strat_cfg.get("name", "simple_maker_taker"))
    current_params = current_strategy_cfg.get("params", yaml_strat_params)

    strategy_name = st.sidebar.selectbox(
        "Estratégia",
        options=strategy_options,
        index=strategy_options.index(current_name) if current_name in strategy_options else 0,
    )

    def param_value(key: str, default: float | int | str) -> Any:
        if key in current_params:
            return current_params[key]
        if key in yaml_strat_params:
            return yaml_strat_params[key]
        return default

    new_params: Dict[str, Any] = dict(current_params)

    # ---- Parâmetros por estratégia (UI) ---- #

    if strategy_name == "simple_maker_taker":
        st.sidebar.markdown("**Simple Maker/Taker**")
        new_params["min_spread"] = st.sidebar.number_input(
            "min_spread", value=float(param_value("min_spread", 1.0)), step=0.1
        )
        new_params["order_size"] = st.sidebar.number_input(
            "order_size", value=float(param_value("order_size", 0.001)), step=0.0001, format="%.6f"
        )
        new_params["tick_interval"] = st.sidebar.number_input(
            "tick_interval", value=int(param_value("tick_interval", 5)), step=1, min_value=1
        )

    elif strategy_name == "market_maker_v1":
        st.sidebar.markdown("**Market Maker V1**")
        new_params["min_spread"] = st.sidebar.number_input(
            "min_spread", value=float(param_value("min_spread", 1.0)), step=0.1
        )
        new_params["max_spread"] = st.sidebar.number_input(
            "max_spread", value=float(param_value("max_spread", 10.0)), step=0.1
        )
        new_params["spread_pct"] = st.sidebar.number_input(
            "spread_pct", value=float(param_value("spread_pct", 0.0)), step=0.0001, format="%.4f"
        )
        new_params["quote_size"] = st.sidebar.number_input(
            "quote_size", value=float(param_value("quote_size", 0.001)), step=0.0001, format="%.6f"
        )
        new_params["tick_interval"] = st.sidebar.number_input(
            "tick_interval", value=int(param_value("tick_interval", 5)), step=1, min_value=1
        )

    elif strategy_name == "market_maker_v2":
        st.sidebar.markdown("**Market Maker V2 (adaptativo)**")
        new_params["min_spread"] = st.sidebar.number_input(
            "min_spread", value=float(param_value("min_spread", 1.0)), step=0.1
        )
        new_params["max_spread"] = st.sidebar.number_input(
            "max_spread", value=float(param_value("max_spread", 15.0)), step=0.1
        )
        new_params["spread_pct"] = st.sidebar.number_input(
            "spread_pct", value=float(param_value("spread_pct", 0.0)), step=0.0001, format="%.4f"
        )
        new_params["quote_size"] = st.sidebar.number_input(
            "quote_size", value=float(param_value("quote_size", 0.001)), step=0.0001, format="%.6f"
        )
        new_params["tick_interval"] = st.sidebar.number_input(
            "tick_interval", value=int(param_value("tick_interval", 5)), step=1, min_value=1
        )
        new_params["vol_window"] = st.sidebar.number_input(
            "vol_window", value=int(param_value("vol_window", 50)), step=1, min_value=5
        )
        new_params["vol_factor"] = st.sidebar.number_input(
            "vol_factor", value=float(param_value("vol_factor", 1.0)), step=0.1
        )

    elif strategy_name == "micro_momentum_v1":
        st.sidebar.markdown("**Micro Momentum V1**")
        new_params["lookback_ticks"] = st.sidebar.number_input(
            "lookback_ticks", value=int(param_value("lookback_ticks", 10)), step=1, min_value=3
        )
        new_params["min_moves"] = st.sidebar.number_input(
            "min_moves", value=int(param_value("min_moves", 3)), step=1, min_value=1
        )
        new_params["min_return"] = st.sidebar.number_input(
            "min_return", value=float(param_value("min_return", 0.0005)), step=0.0001, format="%.4f"
        )
        new_params["order_size"] = st.sidebar.number_input(
            "order_size", value=float(param_value("order_size", 0.001)), step=0.0001, format="%.6f"
        )
        new_params["cooldown_ticks"] = st.sidebar.number_input(
            "cooldown_ticks", value=int(param_value("cooldown_ticks", 10)), step=1, min_value=0
        )
        new_params["side_bias"] = st.sidebar.selectbox(
            "side_bias",
            options=["both", "long_only", "short_only"],
            index=["both", "long_only", "short_only"].index(
                param_value("side_bias", "both")
            ),
        )

    elif strategy_name == "imbalance_v1":
        st.sidebar.markdown("**Imbalance V1**")
        new_params["imbalance_threshold"] = st.sidebar.number_input(
            "imbalance_threshold", value=float(param_value("imbalance_threshold", 0.6)), step=0.05
        )
        new_params["min_total_size"] = st.sidebar.number_input(
            "min_total_size", value=float(param_value("min_total_size", 1.0)), step=0.1
        )
        new_params["imbalance_order_size"] = st.sidebar.number_input(
            "imbalance_order_size", value=float(param_value("imbalance_order_size", 0.001)), step=0.0001, format="%.6f"
        )
        new_params["imbalance_cooldown_ticks"] = st.sidebar.number_input(
            "imbalance_cooldown_ticks",
            value=int(param_value("imbalance_cooldown_ticks", 5)),
            step=1,
            min_value=0,
        )
        new_params["imbalance_side_bias"] = st.sidebar.selectbox(
            "imbalance_side_bias",
            options=["both", "long_only", "short_only"],
            index=["both", "long_only", "short_only"].index(
                param_value("imbalance_side_bias", "both")
            ),
        )

    elif strategy_name == "mean_reversion_v1":
        st.sidebar.markdown("**Mean Reversion V1**")
        new_params["mr_lookback_ticks"] = st.sidebar.number_input(
            "mr_lookback_ticks", value=int(param_value("mr_lookback_ticks", 20)), step=1, min_value=5
        )
        new_params["mr_z_threshold"] = st.sidebar.number_input(
            "mr_z_threshold", value=float(param_value("mr_z_threshold", 2.0)), step=0.1
        )
        new_params["mr_order_size"] = st.sidebar.number_input(
            "mr_order_size", value=float(param_value("mr_order_size", 0.001)), step=0.0001, format="%.6f"
        )
        new_params["mr_cooldown_ticks"] = st.sidebar.number_input(
            "mr_cooldown_ticks",
            value=int(param_value("mr_cooldown_ticks", 10)),
            step=1,
            min_value=0,
        )
        new_params["mr_side_bias"] = st.sidebar.selectbox(
            "mr_side_bias",
            options=["both", "long_only", "short_only"],
            index=["both", "long_only", "short_only"].index(
                param_value("mr_side_bias", "both")
            ),
        )
        new_params["mr_max_z_cap"] = st.sidebar.number_input(
            "mr_max_z_cap", value=float(param_value("mr_max_z_cap", 5.0)), step=0.5
        )

    # Atualiza a strategy_cfg da sessão
    st.session_state.strategy_cfg = {"name": strategy_name, "params": new_params}

    # ------------------------------------------------------------------ #
    # Sidebar: parâmetros de mercado (apenas dummy)
    # ------------------------------------------------------------------ #

    st.sidebar.markdown("---")
    st.sidebar.header("Mercado")

    exchange_override: Dict[str, Any] = dict(st.session_state.exchange_override)

    if provider == "dummy":
        st.sidebar.caption("Ambiente de mercado editável (modo dummy).")

        datafeed_default = base_exchange_cfg.get("datafeed", "dummy_orderbook")
        datafeed_current = exchange_override.get("datafeed", datafeed_default)

        datafeed_type = st.sidebar.selectbox(
            "Tipo de datafeed dummy",
            options=["dummy", "dummy_orderbook"],
            index=["dummy", "dummy_orderbook"].index(datafeed_current)
            if datafeed_current in ["dummy", "dummy_orderbook"]
            else ["dummy", "dummy_orderbook"].index(datafeed_default),
        )
        exchange_override["datafeed"] = datafeed_type

        start_price = st.sidebar.number_input(
            "Preço inicial (mid)",
            value=float(exchange_override.get("start_price", base_exchange_cfg.get("start_price", 100000.0))),
            step=100.0,
            format="%.2f",
        )
        tick_sleep = st.sidebar.number_input(
            "tick_sleep (s)",
            value=float(exchange_override.get("tick_sleep", base_exchange_cfg.get("tick_sleep", 0.0))),
            step=0.01,
            format="%.2f",
            min_value=0.0,
        )

        exchange_override["start_price"] = start_price
        exchange_override["tick_sleep"] = tick_sleep

        if datafeed_type == "dummy_orderbook":
            volatility = st.sidebar.number_input(
                "Volatilidade base (%)",
                value=float(100 * exchange_override.get("volatility", base_exchange_cfg.get("volatility", 0.0005))),
                step=0.01,
                format="%.2f",
            )
            base_spread_ticks = st.sidebar.number_input(
                "Spread médio (ticks)",
                value=float(exchange_override.get("base_spread_ticks", base_exchange_cfg.get("base_spread_ticks", 1.0))),
                step=0.1,
                format="%.2f",
            )
            depth_levels = st.sidebar.number_input(
                "Níveis do book por lado",
                value=int(exchange_override.get("depth_levels", base_exchange_cfg.get("depth_levels", 5))),
                step=1,
                min_value=1,
                max_value=50,
            )
            base_liquidity = st.sidebar.number_input(
                "Liquidez base por nível",
                value=float(exchange_override.get("base_liquidity", base_exchange_cfg.get("base_liquidity", 1.0))),
                step=0.1,
                format="%.2f",
            )

            exchange_override["volatility"] = volatility / 100.0
            exchange_override["base_spread_ticks"] = base_spread_ticks
            exchange_override["depth_levels"] = depth_levels
            exchange_override["base_liquidity"] = base_liquidity

        st.session_state.exchange_override = exchange_override

    else:
        st.sidebar.caption(
            "Parâmetros de mercado são definidos pelo YAML (Binance). "
            "Use APP_ENV + arquivos settings_*.yaml para trocar ambiente."
        )

    # ------------------------------------------------------------------ #
    # Inicialização do engine (primeira vez)
    # ------------------------------------------------------------------ #

    if "engine" not in st.session_state:
        init_engine_and_data(
            st.session_state.strategy_cfg,
            st.session_state.exchange_override if provider == "dummy" else None,
        )

    engine: TradingEngine = st.session_state.engine
    effective_exchange_cfg = st.session_state.get("exchange_effective_cfg", base_exchange_cfg)

    # ------------------------------------------------------------------ #
    # Controles de execução
    # ------------------------------------------------------------------ #

    st.sidebar.markdown("---")
    st.sidebar.header("Execução (modo lab / dummy / binance)")

    st.sidebar.write(f"**Símbolo:** `{effective_exchange_cfg['symbol']}`")
    st.sidebar.write(f"**Provider (YAML):** `{base_exchange_cfg.get('provider', 'dummy')}`")
    st.sidebar.write(f"**Datafeed efetivo:** `{effective_exchange_cfg.get('datafeed', 'dummy')}`")
    st.sidebar.write(f"**Estratégia ativa no engine:** `{st.session_state.strategy_cfg['name']}`")

    step_ticks = st.sidebar.number_input(
        "Nº de ticks por passo",
        min_value=1,
        max_value=5000,
        value=100,
        step=50,
    )

    col_b1, col_b2 = st.sidebar.columns(2)
    if col_b1.button("▶ Rodar", use_container_width=True):
        process_n_ticks(int(step_ticks))

    if col_b2.button("🔁 Resetar (aplicar estratégia/mercado)", use_container_width=True):
        init_engine_and_data(
            st.session_state.strategy_cfg,
            st.session_state.exchange_override if provider == "dummy" else None,
        )
        st.rerun()

    st.sidebar.info(
        "Ao alterar estratégia ou parâmetros de mercado (dummy), clique em **Resetar** "
        "para recriar o engine com essa configuração."
    )

    # Estado do engine
    snap = engine.snapshot()
    st.sidebar.markdown("---")
    st.sidebar.subheader("Estado do Engine")
    st.sidebar.write(f"Running: `{snap['running']}`")
    st.sidebar.write(f"Ticks processados: `{snap['tick_count']}`")
    st.sidebar.write(f"Trades executados: `{snap['trade_count']}`")
    st.sidebar.write(f"Último preço: `{snap['last_price']}`")
    st.sidebar.write(
        f"Posição: `{snap['position']['qty']}` @ `{snap['position']['avg_price']}`"
    )
    st.sidebar.write(f"PnL realizado: `{snap['position']['realized_pnl']}`")
    if snap["last_error"]:
        st.sidebar.error(f"Erro recente: {snap['last_error']}")

    # ------------------------------------------------------------------ #
    # MÉTRICAS GERAIS (topo da página)
    # ------------------------------------------------------------------ #

    metrics = compute_metrics()
    st.subheader("📊 Métricas gerais do robô (sessão atual)")

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("PnL líquido", f"{metrics['net_pnl']:.4f}")
    mc2.metric("Win rate", f"{metrics['win_rate']:.2f}%")
    mc3.metric("Max Drawdown", f"{metrics['max_drawdown']:.4f}")
    mc4.metric("Trades", metrics["total_trades"])

    st.markdown("---")

    # ------------------------------------------------------------------ #
    # Tabs principais
    # ------------------------------------------------------------------ #

    tab_price, tab_pnl, tab_trades, tab_signals, tab_events = st.tabs(
        ["📈 Preço & Book", "💰 PnL / Equity", "📜 Trades", "📡 Sinais", "📝 Eventos"]
    )

    # Tab preço & book
    with tab_price:
        st.subheader("Preço (last, bid, ask) ao longo dos ticks")
        if st.session_state.price_history:
            price_df = pd.DataFrame(st.session_state.price_history)
            price_df = price_df.sort_values("ts").set_index("ts")

            cols_price = [c for c in ["last", "bid", "ask"] if c in price_df.columns]
            if cols_price:
                st.line_chart(price_df[cols_price])
            else:
                st.info("Sem dados de preço suficientes.")

            # Imbalance do book ao longo do tempo
            st.subheader("Imbalance do book ( (bid_size - ask_size) / (total) )")
            if "bid_size" in price_df.columns and "ask_size" in price_df.columns:
                df_imb = price_df[["bid_size", "ask_size"]].copy()
                total = df_imb["bid_size"] + df_imb["ask_size"]
                df_imb["imbalance"] = 0.0
                nonzero = total > 0
                df_imb.loc[nonzero, "imbalance"] = (
                    (df_imb.loc[nonzero, "bid_size"] - df_imb.loc[nonzero, "ask_size"])
                    / total.loc[nonzero]
                )
                st.line_chart(df_imb["imbalance"])
            else:
                st.info("Sem dados de tamanho de book para calcular imbalance.")
        else:
            st.info("Ainda não há dados de preço. Clique em 'Rodar' na barra lateral.")

    # Tab PnL / Equity
    with tab_pnl:
        st.subheader("PnL realizado e Equity (fictícia: 1000 + PnL)")
        if st.session_state.pnl_history:
            pnl_df = pd.DataFrame(st.session_state.pnl_history)
            pnl_df = pnl_df.sort_values("ts").set_index("ts")

            col1, col2 = st.columns(2)
            with col1:
                st.write("PnL realizado")
                st.line_chart(pnl_df["realized_pnl"])
            with col2:
                st.write("Equity (simulada)")
                st.line_chart(pnl_df["equity"])
        else:
            st.info("Ainda não há PnL. Rode alguns ticks para ver os resultados.")

    # Tab trades
    with tab_trades:
        st.subheader("Trades executados (simulados)")
        if st.session_state.trades:
            trades_df = pd.DataFrame(st.session_state.trades)
            st.dataframe(trades_df)
        else:
            st.info("Nenhum trade executado ainda.")

    # Tab sinais
    with tab_signals:
        st.subheader("Últimos sinais da estratégia (snapshot)")
        last_signals = snap["last_signals"]
        if last_signals:
            sig_df = pd.DataFrame(last_signals)
            st.dataframe(sig_df)
        else:
            st.info("Nenhum sinal gerado ainda ou ainda não processado.")

    # Tab eventos
    with tab_events:
        st.subheader("Log de eventos (trades, rejeições, erros, circuit breaker)")
        if st.session_state.event_log:
            events_df = pd.DataFrame(st.session_state.event_log)
            events_df = events_df.sort_values("ts", ascending=False)
            st.dataframe(events_df)
        else:
            st.info("Nenhum evento registrado ainda.")


if __name__ == "__main__":
    main()

# streamlit_app.py

import io
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


# ----------------- Helpers ----------------- #

def init_engine_and_data(strategy_cfg: Dict[str, Any]):
    """
    Inicializa engine, datafeed e históricos na sessão do Streamlit,
    usando a estratégia definida em strategy_cfg (vinda da UI).
    """
    settings = load_settings("config/settings_example.yaml")

    exchange_cfg = settings["exchange"]
    risk_cfg = settings["risk"]
    trading_cfg = settings.get("trading", {})

    symbol = exchange_cfg["symbol"]

    # Constrói componentes core com a estratégia escolhida na UI
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

    st.session_state.engine = engine
    st.session_state.data_iter = data_iter

    # históricos p/ gráficos
    st.session_state.price_history: List[Dict[str, float]] = []
    st.session_state.pnl_history: List[Dict[str, float]] = []
    st.session_state.trades: List[Dict[str, Any]] = []

    # equity fictícia para lab (1000 + realized_pnl)
    st.session_state.initial_equity = 1000.0


def process_n_ticks(n: int):
    """
    Processa N ticks usando o engine e atualiza
    histórico de preço, PnL e trades em session_state.
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

        # Histórico de preço
        st.session_state.price_history.append(
            {"ts": ts, "last": last_price}
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
            elif ev.type == "signal_rejected":
                # Poderíamos salvar aqui se quiser analisar rejeições depois
                pass
            elif ev.type == "circuit_breaker":
                st.warning(f"Circuit breaker disparado: {ev.data.get('message')}")
                return
            elif ev.type == "error":
                st.error(f"Erro na engine: {ev.data.get('message')}")


# ----------------- UI ----------------- #

def main():
    st.set_page_config(page_title="Robô HFT - Lab Streamlit", layout="wide")

    st.title("🤖 Robô HFT – Laboratório em Streamlit (Modo Dummy)")

    # Carrega YAML como base de configuração
    settings = load_settings("config/settings_example.yaml")
    exchange_cfg = settings["exchange"]
    yaml_strat_cfg = settings["strategy"]
    yaml_strat_params = yaml_strat_cfg.get("params", {})

    # Inicializa strategy_cfg na sessão, se ainda não existir
    if "strategy_cfg" not in st.session_state:
        st.session_state.strategy_cfg = {
            "name": yaml_strat_cfg.get("name", "simple_maker_taker"),
            "params": dict(yaml_strat_params),
        }

    # ------------------------------------------- #
    # Sidebar: escolha da estratégia e parâmetros
    # ------------------------------------------- #

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

    # Seleção de estratégia
    strategy_name = st.sidebar.selectbox(
        "Estratégia",
        options=strategy_options,
        index=strategy_options.index(current_name) if current_name in strategy_options else 0,
    )

    # Helper para pegar valor default (prioriza sessão, depois YAML, depois um default passado)
    def param_value(key: str, default: float | int | str) -> Any:
        if key in current_params:
            return current_params[key]
        if key in yaml_strat_params:
            return yaml_strat_params[key]
        return default

    # Parâmetros específicos por estratégia
    new_params: Dict[str, Any] = dict(current_params)

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

    # Atualiza a strategy_cfg da sessão com o que foi definido na sidebar
    st.session_state.strategy_cfg = {"name": strategy_name, "params": new_params}

    # ------------------------------------------- #
    # Inicialização do engine (primeira vez)
    # ------------------------------------------- #

    if "engine" not in st.session_state:
        # Usa a estratégia escolhida na UI para inicializar a engine
        init_engine_and_data(st.session_state.strategy_cfg)

    engine: TradingEngine = st.session_state.engine

    # ------------------------------------------- #
    # Controles adicionais na sidebar
    # ------------------------------------------- #

    st.sidebar.markdown("---")
    st.sidebar.header("Execução (modo lab / dummy)")

    st.sidebar.write(f"**Símbolo:** `{exchange_cfg['symbol']}`")
    st.sidebar.write(f"**Provider (YAML):** `{exchange_cfg.get('provider', 'dummy')}`")
    st.sidebar.write(f"**Datafeed (YAML):** `{exchange_cfg.get('datafeed', 'dummy')}`")
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

    if col_b2.button("🔁 Resetar (aplicar estratégia)", use_container_width=True):
        # Reinicializa engine e históricos com a estratégia atual da UI
        init_engine_and_data(st.session_state.strategy_cfg)
        st.experimental_rerun()

    st.sidebar.info(
        "Ao alterar a estratégia ou parâmetros, clique em **Resetar** "
        "para recriar o engine com essa configuração."
    )

    # ------------------------------------------- #
    # Estado atual do engine
    # ------------------------------------------- #

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

    # ----------------- Layout principal ----------------- #

    tab_price, tab_pnl, tab_trades, tab_signals = st.tabs(
        ["📈 Preço", "💰 PnL / Equity", "📜 Trades", "📡 Últimos sinais"]
    )

    # Tab preço
    with tab_price:
        st.subheader("Preço (last) ao longo dos ticks")
        if st.session_state.price_history:
            price_df = pd.DataFrame(st.session_state.price_history)
            price_df = price_df.sort_values("ts")
            price_df.set_index("ts", inplace=True)
            st.line_chart(price_df["last"])
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
        st.subheader("Últimos sinais da estratégia (instantâneo do engine)")
        last_signals = snap["last_signals"]
        if last_signals:
            sig_df = pd.DataFrame(last_signals)
            st.dataframe(sig_df)
        else:
            st.info("Nenhum sinal gerado ainda ou ainda não processado.")


if __name__ == "__main__":
    main()

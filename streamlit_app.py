import streamlit as st
import pandas as pd
import time
from dataclasses import dataclass, asdict


# ===============================================================
# 1. CONFIGS, DATACLASSES E ESTADO
# ===============================================================

@dataclass
class StrategyConfig:
    name: str = "baseline_hft"
    timeframe: str = "1s"
    max_position_size_usdt: float = 50.0
    max_daily_loss_usdt: float = 20.0
    max_trades_per_day: int = 100
    take_profit_pct: float = 0.10
    stop_loss_pct: float = 0.05
    enabled: bool = False


@dataclass
class RiskConfig:
    hard_daily_loss_limit_usdt: float = 50.0
    hard_max_exposure_usdt: float = 200.0
    max_consecutive_losses: int = 5
    kill_switch_on_breach: bool = True


def init_state():
    defaults = {
        "ambiente": "paper",
        "strategy_cfg": StrategyConfig(),
        "risk_cfg": RiskConfig(),
        "bot_running": False,
        "status_msg": "Robô parado.",
        "log_df": pd.DataFrame(columns=["timestamp", "nivel", "origem", "mensagem"])
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ===============================================================
# 2. LAYOUT – NOVO TEMPLATE PROFISSIONAL
# ===============================================================

def card(title, content):
    st.markdown(
        f"""
        <div style="
            background-color:#1e1e1e;
            border:1px solid #333;
            padding:15px;
            border-radius:10px;
            margin-top:10px;
            box-shadow:0 0 8px rgba(0,0,0,0.25);
        ">
            <h4 style="margin-bottom:10px;">{title}</h4>
            {content}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ===============================================================
# 3. SIDEBAR – AJUSTADO E ORGANIZADO
# ===============================================================

def sidebar_ui():
    st.sidebar.title("⚙️ Configurações do Robô")

    # Ambiente
    st.sidebar.subheader("🌐 Ambiente")
    ambiente = st.sidebar.selectbox(
        "Selecione o ambiente",
        ["Backtest", "Paper Trading", "Live"],
        index=["Backtest", "Paper Trading", "Live"].index(
            "Paper Trading" if st.session_state.ambiente == "paper" else
            "Backtest" if st.session_state.ambiente == "backtest" else
            "Live"
        ),
    )

    st.session_state.ambiente = {
        "Backtest": "backtest",
        "Paper Trading": "paper",
        "Live": "live",
    }[ambiente]

    st.sidebar.markdown(f"**Atual:** `{st.session_state.ambiente}`")
    st.sidebar.markdown("---")

    # Estratégia
    st.sidebar.subheader("📈 Estratégia HFT")

    cfg = st.session_state.strategy_cfg

    cfg.name = st.sidebar.text_input("Nome da estratégia", cfg.name)
    cfg.timeframe = st.sidebar.selectbox("Timeframe", ["1s", "5s", "15s", "1m"])
    cfg.max_position_size_usdt = st.sidebar.number_input("Tamanho máx. (USDT)", 1.0, 100000.0, cfg.max_position_size_usdt)
    cfg.max_daily_loss_usdt = st.sidebar.number_input("Perda diária máx.", 1.0, 100000.0, cfg.max_daily_loss_usdt)
    cfg.max_trades_per_day = st.sidebar.number_input("Máx. trades/dia", 1, 5000, cfg.max_trades_per_day)
    cfg.take_profit_pct = st.sidebar.number_input("TP (%)", 0.01, 5.0, cfg.take_profit_pct)
    cfg.stop_loss_pct = st.sidebar.number_input("SL (%)", 0.01, 5.0, cfg.stop_loss_pct)
    cfg.enabled = st.sidebar.checkbox("Ativar estratégia", cfg.enabled)

    st.session_state.strategy_cfg = cfg
    st.sidebar.markdown("---")

    # Risco
    st.sidebar.subheader("🛡️ Risco Global")

    r = st.session_state.risk_cfg
    r.hard_daily_loss_limit_usdt = st.sidebar.number_input("Hard Loss diário", 1.0, 100000.0, r.hard_daily_loss_limit_usdt)
    r.hard_max_exposure_usdt = st.sidebar.number_input("Exposição máx.", 1.0, 500000.0, r.hard_max_exposure_usdt)
    r.max_consecutive_losses = st.sidebar.number_input("Máx. perdas seguidas", 1, 100, r.max_consecutive_losses)
    r.kill_switch_on_breach = st.sidebar.checkbox("Kill Switch", r.kill_switch_on_breach)

    st.session_state.risk_cfg = r

    st.sidebar.markdown("---")

    # Botões
    if st.sidebar.button("▶️ Iniciar robô"):
        st.session_state.bot_running = True
        st.session_state.status_msg = "Robô rodando."

    if st.sidebar.button("⏹️ Parar robô"):
        st.session_state.bot_running = False
        st.session_state.status_msg = "Robô parado."


# ===============================================================
# 4. STATUS E LOG
# ===============================================================

def render_status():
    running = st.session_state.bot_running
    ambiente = st.session_state.ambiente.upper()

    col1, col2 = st.columns(2)
    col1.metric("Estado", "Rodando" if running else "Parado")
    col2.metric("Ambiente", ambiente)

    st.write(st.session_state.status_msg)

    card("Configuração ativa", f"<pre>{asdict(st.session_state.strategy_cfg)}</pre>")
    card("Risco (hard limits)", f"<pre>{asdict(st.session_state.risk_cfg)}</pre>")


def render_logs():
    df = st.session_state.log_df
    if df.empty:
        st.info("Nenhum log ainda.")
        return
    st.dataframe(df.tail(50), use_container_width=True)


# ===============================================================
# 5. MAIN
# ===============================================================

def main():
    st.set_page_config(layout="wide", page_title="Robô HFT")

    init_state()
    sidebar_ui()

    st.title("🤖 Console do Robô HFT")

    tabs = st.tabs(["📡 Status", "📜 Logs"])

    with tabs[0]:
        render_status()

    with tabs[1]:
        render_logs()


if __name__ == "__main__":
    main()

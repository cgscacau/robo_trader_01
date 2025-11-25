# streamlit_app.py

import time
from dataclasses import dataclass, asdict
from typing import Dict, Any

import pandas as pd
import streamlit as st


# ==========================
# 1. CONFIGURAÇÕES GERAIS
# ==========================

APP_NAME = "Robô Investidor - Console HFT"

AMBIENTES_DISPONIVEIS = {
    "Backtest (simulação)": "backtest",
    "Paper Trading": "paper",
    "Live (conta real)": "live",
}


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


# ==================================
# 2. INICIALIZAÇÃO DO SESSION_STATE
# ==================================

def init_session_state() -> None:
    """Garante que todas as chaves críticas existem no session_state."""

    if "ambiente" not in st.session_state:
        st.session_state.ambiente = "paper"  # default seguro

    if "strategy_cfg" not in st.session_state:
        st.session_state.strategy_cfg = StrategyConfig()

    if "risk_cfg" not in st.session_state:
        st.session_state.risk_cfg = RiskConfig()

    if "bot_running" not in st.session_state:
        st.session_state.bot_running = False

    if "status_msg" not in st.session_state:
        st.session_state.status_msg = "Robô parado."

    if "log_df" not in st.session_state:
        st.session_state.log_df = pd.DataFrame(
            columns=["timestamp", "nivel", "origem", "mensagem"]
        )


# ==========================
# 3. UI DO SIDEBAR
# ==========================

def sidebar_config() -> None:
    st.sidebar.title("⚙️ Configurações")

    # --- Ambiente de operação ---
    st.sidebar.subheader("🌐 Ambiente de operação")

    ambiente_label_default = {
        v: k for k, v in AMBIENTES_DISPONIVEIS.items()
    }.get(st.session_state.ambiente, "Paper Trading")

    ambiente_label = st.sidebar.selectbox(
        "Selecione o ambiente:",
        options=list(AMBIENTES_DISPONIVEIS.keys()),
        index=list(AMBIENTES_DISPONIVEIS.keys()).index(ambiente_label_default),
        help="Backtest = simulação offline, Paper = sem risco real, Live = conta real (máxima proteção).",
    )
    st.session_state.ambiente = AMBIENTES_DISPONIVEIS[ambiente_label]

    st.sidebar.markdown(
        f"**Ambiente atual:** `{st.session_state.ambiente.upper()}`"
    )

    st.sidebar.markdown("---")

    # --- Estratégia ---
    st.sidebar.subheader("📈 Estratégia HFT")

    strategy_name = st.sidebar.text_input(
        "Nome da estratégia",
        value=st.session_state.strategy_cfg.name,
        help="Somente identificador interno (ex: baseline_hft, micro_scalp, etc.)",
    )

    timeframe = st.sidebar.selectbox(
        "Timeframe base",
        options=["1s", "5s", "15s", "1m"],
        index=["1s", "5s", "15s", "1m"].index(
            st.session_state.strategy_cfg.timeframe
            if st.session_state.strategy_cfg.timeframe in ["1s", "5s", "15s", "1m"]
            else "1s"
        ),
    )

    max_pos = st.sidebar.number_input(
        "Tamanho máx. posição (USDT)",
        min_value=1.0,
        max_value=10_000.0,
        value=float(st.session_state.strategy_cfg.max_position_size_usdt),
        step=1.0,
    )

    max_daily_loss = st.sidebar.number_input(
        "Perda diária máx. (USDT)",
        min_value=1.0,
        max_value=50_000.0,
        value=float(st.session_state.strategy_cfg.max_daily_loss_usdt),
        step=1.0,
    )

    max_trades_day = st.sidebar.number_input(
        "Máx. trades por dia",
        min_value=1,
        max_value=10_000,
        value=int(st.session_state.strategy_cfg.max_trades_per_day),
        step=1,
    )

    tp_pct = st.sidebar.number_input(
        "Take Profit (%)",
        min_value=0.01,
        max_value=5.0,
        value=float(st.session_state.strategy_cfg.take_profit_pct),
        step=0.01,
    )

    sl_pct = st.sidebar.number_input(
        "Stop Loss (%)",
        min_value=0.01,
        max_value=5.0,
        value=float(st.session_state.strategy_cfg.stop_loss_pct),
        step=0.01,
    )

    enabled = st.sidebar.checkbox(
        "Estratégia habilitada",
        value=st.session_state.strategy_cfg.enabled,
    )

    # Atualiza o objeto de config no session_state
    st.session_state.strategy_cfg = StrategyConfig(
        name=strategy_name,
        timeframe=timeframe,
        max_position_size_usdt=max_pos,
        max_daily_loss_usdt=max_daily_loss,
        max_trades_per_day=max_trades_day,
        take_profit_pct=tp_pct,
        stop_loss_pct=sl_pct,
        enabled=enabled,
    )

    st.sidebar.markdown("---")

    # --- Risco Global / Circuit Breakers ---
    st.sidebar.subheader("🛡️ Proteção & Circuit Breakers")

    hard_daily_loss = st.sidebar.number_input(
        "Hard Stop - perda diária (USDT)",
        min_value=1.0,
        max_value=100_000.0,
        value=float(st.session_state.risk_cfg.hard_daily_loss_limit_usdt),
        step=1.0,
    )

    hard_exposure = st.sidebar.number_input(
        "Exposição máx. total (USDT)",
        min_value=1.0,
        max_value=1_000_000.0,
        value=float(st.session_state.risk_cfg.hard_max_exposure_usdt),
        step=10.0,
    )

    max_consec_losses = st.sidebar.number_input(
        "Máx. perdas consecutivas",
        min_value=1,
        max_value=100,
        value=int(st.session_state.risk_cfg.max_consecutive_losses),
        step=1,
    )

    kill_on = st.sidebar.checkbox(
        "Ativar kill switch em violação",
        value=st.session_state.risk_cfg.kill_switch_on_breach,
        help="Se violar qualquer limite hard, o robô desliga automaticamente.",
    )

    st.session_state.risk_cfg = RiskConfig(
        hard_daily_loss_limit_usdt=hard_daily_loss,
        hard_max_exposure_usdt=hard_exposure,
        max_consecutive_losses=max_consec_losses,
        kill_switch_on_breach=kill_on,
    )

    st.sidebar.markdown("---")

    # Botões de controle do robô
    st.sidebar.subheader("🧠 Controle do Robô")

    col1, col2 = st.sidebar.columns(2)

    with col1:
        if st.button("▶️ Iniciar robô", use_container_width=True):
            st.session_state.bot_running = True
            st.session_state.status_msg = "Robô em execução."
            log_event("INFO", "ui", "Robô iniciado pelo usuário.")

    with col2:
        if st.button("⏹️ Parar robô", use_container_width=True):
            st.session_state.bot_running = False
            st.session_state.status_msg = "Robô parado."
            log_event("WARN", "ui", "Robô parado pelo usuário.")


# ==========================
# 4. LOG & STATUS
# ==========================

def log_event(level: str, source: str, message: str) -> None:
    """Registra um evento em log_df dentro do session_state."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    new_row = {
        "timestamp": ts,
        "nivel": level,
        "origem": source,
        "mensagem": message,
    }

    st.session_state.log_df = pd.concat(
        [st.session_state.log_df, pd.DataFrame([new_row])],
        ignore_index=True,
    )


def ui_status() -> None:
    st.subheader("📡 Status do Robô")

    col_a, col_b = st.columns(2)

    with col_a:
        st.metric(
            label="Estado atual",
            value="Rodando" if st.session_state.bot_running else "Parado",
        )
        st.caption(st.session_state.status_msg)

    with col_b:
        st.metric(
            label="Ambiente",
            value=st.session_state.ambiente.upper(),
        )

    st.markdown("---")

    st.subheader("⚙️ Configuração ativa da estratégia")
    st.json(asdict(st.session_state.strategy_cfg))

    st.subheader("🛡️ Configuração de risco (hard limits)")
    st.json(asdict(st.session_state.risk_cfg))


def ui_logs() -> None:
    st.subheader("📜 Log de eventos (últimos 50)")

    if st.session_state.log_df.empty:
        st.info("Nenhum evento registrado ainda.")
        return

    df_tail = st.session_state.log_df.tail(50).iloc[::-1].reset_index(drop=True)
    st.dataframe(df_tail, use_container_width=True, height=300)


# ==========================
# 5. LOOP PRINCIPAL (FAKE)
# ==========================

def fake_trading_loop() -> None:
    """
    Aqui NÃO executamos ordens reais.
    É apenas uma simulação para manter a estrutura viva.
    No seu código real, aqui entra:
      - leitura de dados (WebSocket/REST)
      - geração de sinais
      - passagem pelo risk engine
      - envio de ordens
    """

    if not st.session_state.bot_running:
        return

    # Exemplo: logar um 'tick' a cada refresh
    log_event("DEBUG", "loop", "Tick de simulação executado.")


# ==========================
# 6. MAIN
# ==========================

def main() -> None:
    st.set_page_config(
        page_title=APP_NAME,
        layout="wide",
        page_icon="📊",
    )

    init_session_state()

    st.title(APP_NAME)
    st.caption("Arquitetura modular, HFT com múltiplas camadas de proteção e circuit breakers.")

    # Sidebar (ambiente + configs)
    sidebar_config()

    # Loop (por enquanto fake/simulação)
    fake_trading_loop()

    # Abas principais
    tab_status, tab_logs = st.tabs(["📡 Status & Configuração", "📜 Logs"])

    with tab_status:
        ui_status()

    with tab_logs:
        ui_logs()


if __name__ == "__main__":
    main()

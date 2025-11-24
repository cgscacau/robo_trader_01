# core/backtest.py

from dataclasses import dataclass
from typing import Iterable, List, Dict, Any, Optional

from core.position import PositionManager
from core.risk import RiskManager, CircuitBreakerTripped
from core.inventory import InventoryRiskManager, InventoryLimitExceeded
from core.strategy import Signal


@dataclass
class BacktestConfig:
    initial_equity: float = 1000.0
    fee_rate: float = 0.0004      # taxa proporcional sobre o notional
    slippage_bps: float = 0.0     # slippage em basis points (1 bp = 0.01%)


@dataclass
class BacktestTrade:
    ts: float
    side: str
    size: float
    price: float
    fee: float
    pnl: float
    equity_after: float
    signal_tag: str


@dataclass
class BacktestResult:
    trades: List[BacktestTrade]
    equity_curve: List[Dict[str, float]]
    summary: Dict[str, float]


class BacktestEngine:
    """
    Motor de backtest simples, reaproveitando:
    - Strategy (qualquer uma das implementadas)
    - PositionManager
    - RiskManager
    - InventoryRiskManager

    Não chama exchange real. Simula execução:
    - MARKET: usa tick["last"]
    - LIMIT: usa signal.price (assumindo fill imediato simplificado)
    """

    def __init__(
        self,
        symbol: str,
        strategy,
        risk_manager: RiskManager,
        inventory_manager: InventoryRiskManager,
        config: Optional[BacktestConfig] = None,
    ):
        self.symbol = symbol
        self.strategy = strategy
        self.risk = risk_manager
        self.inv_risk = inventory_manager
        self.cfg = config or BacktestConfig()

        self.position = PositionManager()
        self.equity: float = self.cfg.initial_equity

        self._trades: List[BacktestTrade] = []
        self._equity_curve: List[Dict[str, float]] = []

    # ----------------- Helpers ----------------- #

    def _apply_slippage(self, price: float, side: str) -> float:
        """
        Aplica slippage em basis points:
        - BUY: preço piora (aumenta)
        - SELL: preço piora (diminui)
        """
        if self.cfg.slippage_bps <= 0:
            return price

        factor = self.cfg.slippage_bps / 10000.0
        if side == "BUY":
            return price * (1.0 + factor)
        else:
            return price * (1.0 - factor)

    def _record_equity(self, ts: float) -> None:
        self._equity_curve.append({"ts": ts, "equity": self.equity})

    # ----------------- Execução de um sinal ----------------- #

    def _execute_signal(self, signal: Signal, tick: Dict[str, Any]) -> None:
        # Preço de preenchimento simulado
        if signal.order_type == "MARKET":
            fill_price = tick["last"]
        else:
            if signal.price is None:
                raise ValueError("Preço deve ser definido para ordem LIMIT em backtest.")
            fill_price = signal.price

        fill_price = self._apply_slippage(fill_price, signal.side)

        ts = float(tick.get("ts", 0.0))

        # Equity atual antes do trade
        equity_before = self.equity

        # Valida riscos
        notional = abs(signal.size * fill_price)

        # Inventory (baseado na posição atual + trade)
        self.inv_risk.validate_inventory(
            current_qty=self.position.qty,
            trade_side=signal.side,
            trade_qty=signal.size,
            price=fill_price,
            account_equity=equity_before,
        )

        # Risco de tamanho de posição + circuit breaker
        self.risk.validate_position_size(
            account_equity=equity_before,
            position_notional=notional,
        )
        self.risk.increment_open_trades()

        # Taxa de execução
        fee = notional * self.cfg.fee_rate

        # Atualiza posição e PnL
        realized_before = self.position.realized_pnl
        self.position.on_trade(
            side=signal.side,
            qty=signal.size,
            price=fill_price,
        )
        realized_after = self.position.realized_pnl

        trade_pnl = realized_after - realized_before - fee

        # Atualiza equity
        self.equity += trade_pnl

        # Registra no RiskManager
        self.risk.register_trade_pnl(trade_pnl)
        self.risk.decrement_open_trades()

        # Registra trade
        bt_trade = BacktestTrade(
            ts=ts,
            side=signal.side,
            size=signal.size,
            price=fill_price,
            fee=fee,
            pnl=trade_pnl,
            equity_after=self.equity,
            signal_tag=signal.tag,
        )
        self._trades.append(bt_trade)
        self._record_equity(ts)

    # ----------------- Loop principal de backtest ----------------- #

    def run(self, ticks: Iterable[Dict[str, Any]]) -> BacktestResult:
        """
        Executa o backtest sobre um iterável de ticks (dicionários).
        Cada tick deve ter, ao menos:
          - "last"
          - idealmente "ts"
        """
        try:
            for tick in ticks:
                last = tick.get("last")
                if last is None:
                    continue

                signals = self.strategy.on_tick(tick)
                if not signals:
                    continue

                for signal in signals:
                    try:
                        self._execute_signal(signal, tick)
                    except InventoryLimitExceeded:
                        # Trade rejeitado, segue o jogo
                        continue

        except CircuitBreakerTripped:
            # Circuit breaker acionado pelo RiskManager
            pass

        # Snapshot final na curva de equity
        if self._equity_curve:
            final_ts = self._equity_curve[-1]["ts"]
        else:
            final_ts = 0.0
            self._record_equity(final_ts)

        summary = self._build_summary()

        return BacktestResult(
            trades=self._trades,
            equity_curve=self._equity_curve,
            summary=summary,
        )

    # ----------------- Métricas de resumo ----------------- #

    def _build_summary(self) -> Dict[str, float]:
        trades = self._trades
        equity_curve = self._equity_curve

        total_trades = len(trades)
        wins = sum(1 for t in trades if t.pnl > 0)
        losses = sum(1 for t in trades if t.pnl < 0)
        win_rate = (wins / total_trades) * 100.0 if total_trades > 0 else 0.0

        net_pnl = self.equity - self.cfg.initial_equity
        max_drawdown = self._compute_max_drawdown(equity_curve)

        summary = {
            "initial_equity": self.cfg.initial_equity,
            "final_equity": self.equity,
            "net_pnl": net_pnl,
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": win_rate,
            "max_drawdown": max_drawdown,
        }
        return summary

    def _compute_max_drawdown(self, equity_curve: List[Dict[str, float]]) -> float:
        if not equity_curve:
            return 0.0

        max_equity = equity_curve[0]["equity"]
        max_dd = 0.0

        for point in equity_curve:
            eq = point["equity"]
            if eq > max_equity:
                max_equity = eq
            drawdown = max_equity - eq
            if drawdown > max_dd:
                max_dd = drawdown

        return max_dd

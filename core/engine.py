# core/engine.py

from dataclasses import dataclass
from typing import List, Dict, Any, Optional

import logging

from core.strategy import StrategyBase, Signal
from core.risk import RiskManager, CircuitBreakerTripped
from core.inventory import InventoryRiskManager, InventoryLimitExceeded
from core.position import PositionManager
from core.execution import ExecutionClient


@dataclass
class EngineEvent:
    """
    Evento gerado pelo TradingEngine a cada tick/processamento.

    type:
      - "trade_executed"
      - "signal_rejected"
      - "circuit_breaker"
      - "error"
    data:
      - dicionário com as informações específicas do evento.
    """
    type: str
    data: Dict[str, Any]


class TradingEngine:
    """
    Orquestrador do fluxo:
      tick -> estratégia -> risco/inventário -> execução -> posição -> eventos.

    Essa classe NÃO sabe nada de Streamlit, CLI, etc.
    Ela apenas recebe:
      - tick (dict),
      - executa a lógica,
      - devolve uma lista de EngineEvent para quem estiver consumindo.
    """

    def __init__(
        self,
        symbol: str,
        strategy: StrategyBase,
        risk_manager: RiskManager,
        inventory_manager: InventoryRiskManager,
        execution_client: ExecutionClient,
        position_manager: Optional[PositionManager] = None,
        logger: Optional[logging.Logger] = None,
        raise_on_circuit_breaker: bool = True,
    ):
        self.symbol = symbol
        self.strategy = strategy
        self.risk = risk_manager
        self.inv_risk = inventory_manager
        self.exec_client = execution_client
        self.position = position_manager or PositionManager()
        self.logger = logger or logging.getLogger("trading_engine")
        self.raise_on_circuit_breaker = raise_on_circuit_breaker

        # Estado interno básico
        self.tick_count: int = 0
        self.trade_count: int = 0
        self.running: bool = True

        self.last_tick: Optional[Dict[str, Any]] = None
        self.last_signals: List[Signal] = []
        self.last_error: Optional[str] = None
        self.last_equity: Optional[float] = None

    # ------------------------------------------------------------------ #
    # API principal
    # ------------------------------------------------------------------ #

    def process_tick(self, tick: Dict[str, Any]) -> List[EngineEvent]:
        """
        Processa um único tick:
          - Chama a estratégia.
          - Valida risco e inventário.
          - Executa ordens (ou simula, dependendo do ExecutionClient).
          - Atualiza posição e PnL.
          - Gera eventos (EngineEvent) descrevendo o que aconteceu.

        Retorna:
          Lista de EngineEvent ocorridos neste tick.
        """
        events: List[EngineEvent] = []

        if not self.running:
            # Engine parado (por circuit breaker, por exemplo).
            return events

        self.tick_count += 1
        self.last_tick = tick
        self.last_error = None

        last_price = tick.get("last")
        if last_price is None:
            # Sem preço não dá pra operar; apenas ignora o tick.
            return events

        try:
            signals = self.strategy.on_tick(tick) or []
            self.last_signals = signals
        except Exception as e:
            msg = f"Erro ao executar estratégia: {e}"
            self.last_error = msg
            self.logger.exception(msg)
            events.append(EngineEvent(type="error", data={"message": msg}))
            return events

        if not signals:
            return events

        for signal in signals:
            try:
                self._process_signal(signal, tick, events)
            except CircuitBreakerTripped as cb:
                # Circuit breaker disparou dentro do processamento do sinal.
                self.running = False
                msg = f"Circuit breaker disparado: {cb}"
                self.last_error = msg
                self.logger.error(msg)

                events.append(
                    EngineEvent(
                        type="circuit_breaker",
                        data={"message": str(cb)},
                    )
                )

                if self.raise_on_circuit_breaker:
                    # Propaga para quem estiver controlando o loop externo.
                    raise
                else:
                    # Não propaga; apenas para a engine.
                    break
            except Exception as e:
                msg = f"Erro ao processar sinal: {e}"
                self.last_error = msg
                self.logger.exception(msg)
                events.append(
                    EngineEvent(
                        type="error",
                        data={
                            "message": msg,
                            "signal_side": getattr(signal, "side", None),
                            "signal_size": getattr(signal, "size", None),
                            "signal_tag": getattr(signal, "tag", None),
                        },
                    )
                )
                # continua para o próximo sinal

        return events

    # ------------------------------------------------------------------ #
    # Processamento de um único sinal
    # ------------------------------------------------------------------ #

    def _process_signal(
        self,
        signal: Signal,
        tick: Dict[str, Any],
        events: List[EngineEvent],
    ) -> None:
        """
        Processa um único Signal:
          - obtém preço de preenchimento,
          - consulta equity,
          - valida inventário e risco,
          - executa ordem,
          - atualiza posição e PnL,
          - gera EngineEvent de trade ou rejeição.
        """

        # Determina o preço de preenchimento (fill_price)
        if signal.order_type == "MARKET":
            fill_price = tick["last"]
        else:
            # Para LIMIT, espera que o preço esteja no próprio sinal.
            if signal.price is None:
                raise ValueError(
                    "Sinal LIMIT sem preço definido (signal.price is None)."
                )
            fill_price = signal.price

        # Equity atual da conta (mock ou real)
        equity = self.exec_client.get_account_equity()
        self.last_equity = equity

        # Validação de inventário
        try:
            self.inv_risk.validate_inventory(
                current_qty=self.position.qty,
                trade_side=signal.side,
                trade_qty=signal.size,
                price=fill_price,
                account_equity=equity,
            )
        except InventoryLimitExceeded as inv_err:
            msg = f"Trade rejeitado por limite de inventário: {inv_err}"
            self.logger.warning(msg)
            events.append(
                EngineEvent(
                    type="signal_rejected",
                    data={
                        "reason": "inventory_limit_exceeded",
                        "error": str(inv_err),
                        "side": signal.side,
                        "size": signal.size,
                        "price": fill_price,
                        "signal_tag": signal.tag,
                    },
                )
            )
            return

        # Validação de tamanho de posição / circuit breaker
        notional = abs(signal.size * fill_price)
        self.risk.validate_position_size(
            account_equity=equity,
            position_notional=notional,
        )
        self.risk.increment_open_trades()

        # Execução da ordem (ou simulação, dependendo do ExecutionClient)
        order_res = self.exec_client.send_order(self.symbol, signal)

        # Atualiza posição e PnL
        realized_before = self.position.realized_pnl
        self.position.on_trade(
            side=signal.side,
            qty=signal.size,
            price=fill_price,
        )
        realized_after = self.position.realized_pnl
        trade_pnl = realized_after - realized_before

        # Atualiza RiskManager
        self.risk.register_trade_pnl(trade_pnl)
        self.risk.decrement_open_trades()

        self.trade_count += 1

        # Snapshot de posição
        pos_snap = self.position.snapshot()

        # Evento de trade executado
        events.append(
            EngineEvent(
                type="trade_executed",
                data={
                    "symbol": self.symbol,
                    "side": signal.side,
                    "size": signal.size,
                    "price": fill_price,
                    "signal_tag": signal.tag,
                    "order_response": order_res,
                    "trade_pnl": trade_pnl,
                    "realized_pnl_total": pos_snap.realized_pnl,
                    "position_qty": pos_snap.qty,
                    "position_avg_price": pos_snap.avg_price,
                    "equity": equity,
                },
            )
        )

        # Log estruturado (opcional, mas ajuda diagnóstico)
        self.logger.info(
            "Trade executado pelo TradingEngine.",
            extra={
                "symbol": self.symbol,
                "side": signal.side,
                "size": signal.size,
                "price": fill_price,
                "signal_tag": signal.tag,
                "trade_pnl": trade_pnl,
                "realized_pnl_total": pos_snap.realized_pnl,
                "position_qty": pos_snap.qty,
                "position_avg_price": pos_snap.avg_price,
                "equity": equity,
            },
        )

    # ------------------------------------------------------------------ #
    # Snapshot para UI / monitoramento
    # ------------------------------------------------------------------ #

    def snapshot(self) -> Dict[str, Any]:
        """
        Retorna um snapshot serializável do estado atual do engine, útil
        para dashboards, Streamlit, monitoramentos, etc.
        """
        pos_snap = self.position.snapshot()

        return {
            "symbol": self.symbol,
            "running": self.running,
            "tick_count": self.tick_count,
            "trade_count": self.trade_count,
            "last_price": self.last_tick.get("last") if self.last_tick else None,
            "last_equity": self.last_equity,
            "position": {
                "qty": pos_snap.qty,
                "avg_price": pos_snap.avg_price,
                "realized_pnl": pos_snap.realized_pnl,
            },
            "last_error": self.last_error,
            "last_signals": [
                {
                    "side": s.side,
                    "size": s.size,
                    "order_type": s.order_type,
                    "price": s.price,
                    "tag": s.tag,
                }
                for s in self.last_signals
            ],
        }

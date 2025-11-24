# core/execution.py

from typing import Dict, Any
from .strategy import Signal


class ExecutionClient:
    """
    Camada de execução de ordens.
    Aqui, futuramente, você pluga a API da Binance.
    """

    def __init__(self, base_url: str, api_key: str, api_secret: str, testnet: bool = True):
        self.base_url = base_url
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet

    def send_order(self, symbol: str, signal: Signal) -> Dict[str, Any]:
        """
        Recebe um Signal e envia a ordem para a corretora.
        Por enquanto, só faz log e retorna uma resposta fake.
        """
        # Aqui depois entra a chamada real: assinatura HMAC,
        # endpoint /order, etc.
        print(
            f"[EXEC] Enviando ordem: {signal.side} {signal.size} {symbol} "
            f"tipo={signal.order_type} price={signal.price}"
        )
        fake_response = {
            "status": "FILLED",
            "symbol": symbol,
            "side": signal.side,
            "executed_qty": signal.size,
            "price": signal.price,
        }
        return fake_response

    def get_account_equity(self) -> float:
        """
        Retorna equity da conta (mock por enquanto).
        Depois: chama /account ou similar da Binance.
        """
        return 1000.0  # valor fictício enquanto montamos a arquitetura

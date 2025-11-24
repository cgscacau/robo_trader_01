# core/execution_binance.py

import time
from typing import Dict, Any

import requests

from core.strategy import Signal
from core.binance_utils import sign_params
import logging

logger = logging.getLogger(__name__)


class BinanceExecutionClient:
    """
    Cliente de execução para Binance (Spot ou Futures).
    Se dry_run=True, NÃO envia ordens reais, apenas simula.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        market_type: str = "futures",
        testnet: bool = True,
        recv_window: int = 5000,
        dry_run: bool = False,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.market_type = market_type
        self.recv_window = recv_window
        self.dry_run = dry_run

        if market_type not in ("spot", "futures"):
            raise ValueError("market_type deve ser 'spot' ou 'futures'.")

        if market_type == "spot":
            self.base_url = (
                "https://testnet.binance.vision" if testnet else "https://api.binance.com"
            )
            self._order_endpoint = "/api/v3/order"
            self._account_endpoint = "/api/v3/account"
        else:
            # Futures USDT-M
            self.base_url = (
                "https://testnet.binancefuture.com"
                if testnet
                else "https://fapi.binance.com"
            )
            self._order_endpoint = "/fapi/v1/order"
            self._account_endpoint = "/fapi/v2/account"

    # --------- Helpers HTTP --------- #

    def _headers(self) -> Dict[str, str]:
        return {
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded"
        }

    def _signed_post(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self.recv_window
        params["signature"] = sign_params(params, self.api_secret)

        url = self.base_url + endpoint
        resp = requests.post(url, headers=self._headers(), params=params, timeout=5)
        resp.raise_for_status()
        return resp.json()

    def _signed_get(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self.recv_window
        params["signature"] = sign_params(params, self.api_secret)

        url = self.base_url + endpoint
        resp = requests.get(url, headers=self._headers(), params=params, timeout=5)
        resp.raise_for_status()
        return resp.json()

    # --------- Interface pública --------- #

    def send_order(self, symbol: str, signal: Signal) -> Dict[str, Any]:
        """
        Converte um Signal em parâmetros de ordem Binance e envia.
        Se dry_run=True, não faz request HTTP e retorna resposta simulada.
        """

        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": signal.side,
            "type": "LIMIT" if signal.order_type == "LIMIT" else "MARKET",
            "quantity": self._format_qty(signal.size),
        }

        if signal.order_type == "LIMIT":
            if signal.price is None:
                raise ValueError("Preço é obrigatório para ordem LIMIT.")
            params["price"] = self._format_price(signal.price)
            params["timeInForce"] = "GTC"

        if self.dry_run:
            logger.info(
                "Dry-run ativo: simulando envio de ordem Binance.",
                extra={"symbol": symbol, "params": params, "dry_run": True},
            )
            fake_response = {
                "status": "DRY_RUN",
                "symbol": symbol,
                "side": params["side"],
                "type": params["type"],
                "quantity": params["quantity"],
                "price": params.get("price"),
            }
            return fake_response

        data = self._signed_post(self._order_endpoint, params)
        logger.info(
            "Ordem enviada para Binance.",
            extra={"symbol": symbol, "response": data, "dry_run": False},
        )
        return data

    def get_account_equity(self) -> float:
        """
        Retorna um valor de equity simplificado.
        Se dry_run=True, retorna um valor fixo (ex.: 1000 USDT).
        """
        if self.dry_run:
            return 1000.0

        data = self._signed_get(self._account_endpoint, {})

        if self.market_type == "spot":
            balances = data.get("balances", [])
            equity = 0.0
            for b in balances:
                if b["asset"] == "USDT":
                    free = float(b["free"])
                    locked = float(b["locked"])
                    equity = free + locked
                    break
            return equity
        else:
            return float(data.get("totalWalletBalance", 0.0))

    # --------- Format helpers --------- #

    def _format_qty(self, qty: float) -> str:
        return f"{qty:.6f}".rstrip("0").rstrip(".")

    def _format_price(self, price: float) -> str:
        return f"{price:.2f}"

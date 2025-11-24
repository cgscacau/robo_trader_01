# core/binance_utils.py

import hmac
import hashlib
import urllib.parse
from typing import Dict


def build_query_string(params: Dict) -> str:
    """
    Converte um dict em query string no formato esperado pela Binance.
    Mantém a ordem de inserção (Python 3.7+).
    """
    return urllib.parse.urlencode(params, doseq=True)


def sign_params(params: Dict, api_secret: str) -> str:
    """
    Gera a assinatura HMAC-SHA256 da query string.
    """
    query = build_query_string(params)
    signature = hmac.new(
        api_secret.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return signature

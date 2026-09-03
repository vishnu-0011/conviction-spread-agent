"""GET-only broker-state reconciliation for the first paper canary.

The canary intentionally requires an entirely flat paper account. This makes the
first broker write easy to audit: every resulting position and open order must have
come from the exact preview approved by the operator.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from time import sleep
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PAPER_API_HOST = "https://paper-api.alpaca.markets"
USER_AGENT = "conviction-spread-agent-reconciliation/0.1"


class AlpacaReconciliationError(RuntimeError):
    """A sanitized failure while reading paper broker state."""


JsonValue = dict[str, Any] | list[Any]
JsonTransport = Callable[[Request, int], JsonValue]


def _default_transport(request: Request, timeout_seconds: int) -> JsonValue:
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        payload = json.load(response)
    if not isinstance(payload, (dict, list)):
        raise AlpacaReconciliationError("Alpaca returned unsupported JSON")
    return payload


class AlpacaPaperStateClient:
    """Narrow GET-only client for account, position, and open-order state."""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        timeout_seconds: int = 20,
        maximum_attempts: int = 3,
        retry_delay_seconds: float = 0.5,
        transport: JsonTransport = _default_transport,
    ) -> None:
        if not api_key.strip() or not secret_key.strip():
            raise ValueError("Alpaca API key and secret are required")
        if timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
        if maximum_attempts <= 0:
            raise ValueError("maximum attempts must be positive")
        if retry_delay_seconds < 0:
            raise ValueError("retry delay cannot be negative")
        self.__api_key = api_key
        self.__secret_key = secret_key
        self.__timeout_seconds = timeout_seconds
        self.__maximum_attempts = maximum_attempts
        self.__retry_delay_seconds = retry_delay_seconds
        self.__transport = transport

    def __get(self, path: str, *, query: dict[str, object] | None = None) -> JsonValue:
        values = {
            key: str(value)
            for key, value in (query or {}).items()
            if value is not None
        }
        url = f"{PAPER_API_HOST}{path}"
        if values:
            url = f"{url}?{urlencode(values)}"
        request = Request(
            url,
            method="GET",
            headers={
                "APCA-API-KEY-ID": self.__api_key,
                "APCA-API-SECRET-KEY": self.__secret_key,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        for attempt in range(1, self.__maximum_attempts + 1):
            try:
                return self.__transport(request, self.__timeout_seconds)
            except HTTPError as exc:
                request_id = exc.headers.get("X-Request-ID") if exc.headers else None
                suffix = f" (request id {request_id})" if request_id else ""
                raise AlpacaReconciliationError(
                    f"Alpaca reconciliation GET returned HTTP {exc.code}{suffix}"
                ) from exc
            except (URLError, TimeoutError) as exc:
                if attempt >= self.__maximum_attempts:
                    raise AlpacaReconciliationError(
                        "Alpaca reconciliation GET transport failed after "
                        f"{attempt} attempts"
                    ) from exc
                sleep(self.__retry_delay_seconds * attempt)

    def account(self) -> dict[str, Any]:
        payload = self.__get("/v2/account")
        if not isinstance(payload, dict):
            raise AlpacaReconciliationError("account response is not an object")
        return payload

    def positions(self) -> tuple[dict[str, Any], ...]:
        payload = self.__get("/v2/positions")
        if not isinstance(payload, list):
            raise AlpacaReconciliationError("positions response is not an array")
        return tuple(item for item in payload if isinstance(item, dict))

    def open_orders(self) -> tuple[dict[str, Any], ...]:
        payload = self.__get(
            "/v2/orders",
            query={"status": "open", "nested": "true", "limit": 500},
        )
        if not isinstance(payload, list):
            raise AlpacaReconciliationError("open-orders response is not an array")
        return tuple(item for item in payload if isinstance(item, dict))


def _decimal(value: object, *, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not numeric") from exc
    if parsed < 0:
        raise ValueError(f"{field} cannot be negative")
    return parsed


@dataclass(frozen=True)
class CanaryBrokerState:
    reconciled: bool
    reasons: tuple[str, ...]
    equity: Decimal | None
    previous_equity: Decimal | None
    options_buying_power: Decimal | None
    open_position_count: int
    open_order_count: int
    account_fingerprint: str | None

    def public_record(self) -> dict[str, object]:
        return {
            "reconciled": self.reconciled,
            "reasons": list(self.reasons),
            "open_position_count": self.open_position_count,
            "open_order_count": self.open_order_count,
            "equity_available": self.equity is not None,
            "previous_equity_available": self.previous_equity is not None,
            "options_buying_power_available": self.options_buying_power is not None,
            "account_fingerprint": self.account_fingerprint,
            "account_identifier_emitted": False,
        }


def reconcile_flat_canary_account(
    account: dict[str, Any],
    positions: tuple[dict[str, Any], ...],
    open_orders: tuple[dict[str, Any], ...],
) -> CanaryBrokerState:
    """Reconcile a fresh, entirely flat paper account for its first canary."""

    reasons: list[str] = []
    if str(account.get("status", "")).upper() != "ACTIVE":
        reasons.append("paper account is not active")
    if bool(account.get("account_blocked")) or bool(account.get("trading_blocked")):
        reasons.append("paper account is blocked")
    try:
        options_level = int(account.get("options_trading_level", 0))
    except (TypeError, ValueError):
        options_level = 0
    if options_level < 3:
        reasons.append("options trading level 3 is required")
    if positions:
        reasons.append("the first canary requires a completely flat paper account")
    if open_orders:
        reasons.append("the first canary requires no open broker orders")

    equity = _decimal(account.get("equity"), field="account equity")
    previous_equity = _decimal(
        account.get("last_equity"), field="previous account equity"
    )
    options_buying_power = _decimal(
        account.get("options_buying_power"), field="options buying power"
    )
    if equity is None or equity <= 0:
        reasons.append("positive account equity is required")
    if previous_equity is None or previous_equity <= 0:
        reasons.append("positive previous account equity is required")
    if options_buying_power is None or options_buying_power <= 0:
        reasons.append("positive options buying power is required")

    raw_account_id = str(account.get("id", "")).strip()
    fingerprint = (
        hashlib.sha256(raw_account_id.encode("utf-8")).hexdigest()[:12]
        if raw_account_id
        else None
    )
    if fingerprint is None:
        reasons.append("paper account id is unavailable")

    unique_reasons = tuple(dict.fromkeys(reasons))
    return CanaryBrokerState(
        reconciled=not unique_reasons,
        reasons=unique_reasons,
        equity=equity,
        previous_equity=previous_equity,
        options_buying_power=options_buying_power,
        open_position_count=len(positions),
        open_order_count=len(open_orders),
        account_fingerprint=fingerprint,
    )

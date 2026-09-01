"""Minimal GET-only Alpaca adapter for live paper shadow scans.

The class intentionally exposes no generic request method and no order, position,
exercise, cancel, or replace operation.  All public methods map to documented read
endpoints and the HTTP method is fixed to GET at the only network boundary.
"""

from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


PAPER_API_HOST = "https://paper-api.alpaca.markets"
MARKET_DATA_HOST = "https://data.alpaca.markets"
USER_AGENT = "conviction-spread-agent-shadow/0.1"


class AlpacaReadError(RuntimeError):
    """A sanitized failure from a read-only Alpaca request."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class AlpacaReadOnlyClient:
    """Small Alpaca client whose complete network surface is GET-only."""

    def __init__(self, api_key: str, secret_key: str, *, timeout_seconds: int = 20) -> None:
        if not api_key.strip() or not secret_key.strip():
            raise ValueError("Alpaca API key and secret are required")
        if timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
        self.__api_key = api_key
        self.__secret_key = secret_key
        self.__timeout_seconds = timeout_seconds

    def __get_json(
        self,
        host: str,
        path: str,
        *,
        query_values: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        query = {
            key: str(value)
            for key, value in (query_values or {}).items()
            if value is not None
        }
        url = f"{host}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
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
        try:
            with urlopen(request, timeout=self.__timeout_seconds) as response:  # noqa: S310
                payload = json.load(response)
        except HTTPError as exc:
            request_id = exc.headers.get("X-Request-ID") if exc.headers else None
            suffix = f" (request id {request_id})" if request_id else ""
            raise AlpacaReadError(
                f"Alpaca GET returned HTTP {exc.code}{suffix}", status=exc.code
            ) from exc
        except URLError as exc:
            raise AlpacaReadError(f"Could not reach Alpaca: {exc.reason}") from exc
        except TimeoutError as exc:
            raise AlpacaReadError("Alpaca GET timed out") from exc
        if not isinstance(payload, dict):
            raise AlpacaReadError("Alpaca GET returned a non-object JSON response")
        return payload

    def account(self) -> dict[str, Any]:
        return self.__get_json(PAPER_API_HOST, "/v2/account")

    def clock(self) -> dict[str, Any]:
        return self.__get_json(PAPER_API_HOST, "/v2/clock")

    def stock_snapshot(self, symbol: str, *, feed: str = "iex") -> dict[str, Any]:
        normalized = quote(symbol.strip().upper(), safe="")
        if not normalized:
            raise ValueError("stock symbol is required")
        return self.__get_json(
            MARKET_DATA_HOST,
            f"/v2/stocks/{normalized}/snapshot",
            query_values={"feed": feed},
        )

    def stock_bars(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        feed: str = "iex",
        limit: int = 1000,
    ) -> dict[str, Any]:
        normalized = quote(symbol.strip().upper(), safe="")
        if not normalized:
            raise ValueError("stock symbol is required")
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("bar start must be timezone-aware")
        if end.tzinfo is None or end.utcoffset() is None:
            raise ValueError("bar end must be timezone-aware")
        if end <= start:
            raise ValueError("bar end must be after start")

        bars: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            payload = self.__get_json(
                MARKET_DATA_HOST,
                f"/v2/stocks/{normalized}/bars",
                query_values={
                    "timeframe": "1Day",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "adjustment": "all",
                    "feed": feed,
                    "limit": limit,
                    "page_token": page_token,
                },
            )
            raw_bars = payload.get("bars")
            if not isinstance(raw_bars, list):
                raise AlpacaReadError("stock bars response is missing its bars array")
            bars.extend(item for item in raw_bars if isinstance(item, dict))
            next_token = payload.get("next_page_token")
            if not next_token:
                break
            page_token = str(next_token)
        return {"bars": bars}

    def option_contracts(
        self,
        underlying: str,
        *,
        right: str,
        expiration_from: date,
        expiration_to: date,
        strike_from: str,
        strike_to: str,
        limit: int = 1000,
    ) -> tuple[dict[str, Any], ...]:
        normalized = underlying.strip().upper()
        if not normalized:
            raise ValueError("underlying is required")
        contracts: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            payload = self.__get_json(
                PAPER_API_HOST,
                "/v2/options/contracts",
                query_values={
                    "underlying_symbols": normalized,
                    "status": "active",
                    "type": right,
                    "expiration_date_gte": expiration_from.isoformat(),
                    "expiration_date_lte": expiration_to.isoformat(),
                    "strike_price_gte": strike_from,
                    "strike_price_lte": strike_to,
                    "limit": limit,
                    "page_token": page_token,
                },
            )
            raw_contracts = payload.get("option_contracts", payload.get("contracts"))
            if not isinstance(raw_contracts, list):
                raise AlpacaReadError("option contracts response is missing its contract array")
            contracts.extend(item for item in raw_contracts if isinstance(item, dict))
            next_token = payload.get("next_page_token")
            if not next_token:
                break
            page_token = str(next_token)
        return tuple(contracts)

    def option_chain(
        self,
        underlying: str,
        *,
        right: str,
        expiration_from: date,
        expiration_to: date,
        strike_from: str,
        strike_to: str,
        feed: str = "indicative",
        limit: int = 1000,
    ) -> dict[str, dict[str, Any]]:
        normalized = quote(underlying.strip().upper(), safe="")
        if not normalized:
            raise ValueError("underlying is required")
        snapshots: dict[str, dict[str, Any]] = {}
        page_token: str | None = None
        while True:
            payload = self.__get_json(
                MARKET_DATA_HOST,
                f"/v1beta1/options/snapshots/{normalized}",
                query_values={
                    "feed": feed,
                    "type": right,
                    "expiration_date_gte": expiration_from.isoformat(),
                    "expiration_date_lte": expiration_to.isoformat(),
                    "strike_price_gte": strike_from,
                    "strike_price_lte": strike_to,
                    "limit": limit,
                    "page_token": page_token,
                },
            )
            raw_snapshots = payload.get("snapshots", payload)
            if not isinstance(raw_snapshots, dict):
                raise AlpacaReadError("option chain response is missing its snapshots object")
            for symbol, snapshot in raw_snapshots.items():
                if isinstance(snapshot, dict):
                    snapshots[str(symbol).upper()] = snapshot
            next_token = payload.get("next_page_token")
            if not next_token:
                break
            page_token = str(next_token)
        return snapshots

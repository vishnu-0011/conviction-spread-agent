"""Read-only Alpaca paper-account and options-data preflight.

Only GET requests are issued. The script never prints credentials or full account
identifiers and refuses to run when paper mode is not explicitly enabled.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PAPER_API_HOST = "https://paper-api.alpaca.markets"
MARKET_DATA_HOST = "https://data.alpaca.markets"
USER_AGENT = "conviction-spread-agent-preflight/0.1"


class ApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def load_local_env(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding process environment."""

    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _mask(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)
    return "*" * min(8, len(text) - 4) + text[-4:]


def _get_json(
    host: str,
    path: str,
    *,
    api_key: str,
    secret_key: str,
    query: dict[str, str] | None = None,
    timeout_seconds: int = 20,
) -> tuple[dict[str, Any], dict[str, str]]:
    url = f"{host}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    request = Request(
        url,
        method="GET",
        headers={
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            payload = json.load(response)
            headers = {key.lower(): value for key, value in response.headers.items()}
            if not isinstance(payload, dict):
                raise ApiError("Alpaca returned a non-object JSON response")
            return payload, headers
    except HTTPError as exc:
        request_id = exc.headers.get("X-Request-ID") if exc.headers else None
        suffix = f" (request id {request_id})" if request_id else ""
        raise ApiError(f"Alpaca returned HTTP {exc.code}{suffix}", status=exc.code) from exc
    except URLError as exc:
        raise ApiError(f"Could not reach Alpaca: {exc.reason}") from exc
    except TimeoutError as exc:
        raise ApiError("Alpaca request timed out") from exc


def _as_decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _extract_contracts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("option_contracts", payload.get("contracts", []))
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _extract_snapshots(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = payload.get("snapshots", payload)
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)}


def _account_summary(account: dict[str, Any]) -> dict[str, Any]:
    return {
        "id_masked": _mask(account.get("id")),
        "account_number_masked": _mask(account.get("account_number")),
        "status": account.get("status"),
        "trading_blocked": account.get("trading_blocked"),
        "account_blocked": account.get("account_blocked"),
        "options_approved_level": account.get("options_approved_level"),
        "options_trading_level": account.get("options_trading_level"),
        "options_buying_power": account.get("options_buying_power"),
    }


def _check(name: str, passed: bool, detail: str, *, critical: bool = True) -> dict[str, Any]:
    return {"name": name, "passed": passed, "critical": critical, "detail": detail}


def run_preflight(api_key: str, secret_key: str, underlying: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    account, account_headers = _get_json(
        PAPER_API_HOST, "/v2/account", api_key=api_key, secret_key=secret_key
    )
    summary = _account_summary(account)
    checks.append(_check("paper_authentication", True, "Paper account endpoint authenticated."))
    checks.append(
        _check(
            "account_active",
            str(account.get("status", "")).upper() == "ACTIVE",
            f"Account status is {account.get('status')!r}.",
        )
    )
    blocked = bool(account.get("trading_blocked")) or bool(account.get("account_blocked"))
    checks.append(_check("account_unblocked", not blocked, f"Blocked flags evaluate to {blocked}."))
    option_level = _as_int(account.get("options_trading_level"))
    checks.append(
        _check(
            "options_level_3",
            option_level is not None and option_level >= 3,
            f"Configured options trading level is {option_level!r}; spreads require Level 3.",
        )
    )
    buying_power = _as_decimal(account.get("options_buying_power"))
    checks.append(
        _check(
            "options_buying_power",
            buying_power is not None and buying_power > 0,
            "Options buying power is positive."
            if buying_power is not None and buying_power > 0
            else "Options buying power is absent, invalid, or zero.",
        )
    )

    clock, clock_headers = _get_json(
        PAPER_API_HOST, "/v2/clock", api_key=api_key, secret_key=secret_key
    )
    checks.append(
        _check(
            "market_clock",
            bool(clock.get("timestamp")) and "is_open" in clock,
            "Broker clock returned timestamp and session state.",
        )
    )

    start = date.today() + timedelta(days=14)
    end = date.today() + timedelta(days=35)
    contracts_payload, contract_headers = _get_json(
        PAPER_API_HOST,
        "/v2/options/contracts",
        api_key=api_key,
        secret_key=secret_key,
        query={
            "underlying_symbols": underlying,
            "status": "active",
            "expiration_date_gte": start.isoformat(),
            "expiration_date_lte": end.isoformat(),
            "limit": "100",
        },
    )
    contracts = _extract_contracts(contracts_payload)
    tradable = [contract for contract in contracts if contract.get("tradable") is True]
    checks.append(
        _check(
            "option_contract_discovery",
            bool(tradable),
            f"Found {len(contracts)} contracts and {len(tradable)} explicitly tradable contracts "
            f"for {underlying} in the 14–35 DTE window.",
        )
    )

    symbols = [str(contract.get("symbol")) for contract in tradable[:10] if contract.get("symbol")]
    snapshots: dict[str, dict[str, Any]] = {}
    snapshot_headers: dict[str, str] = {}
    if symbols:
        snapshot_payload, snapshot_headers = _get_json(
            MARKET_DATA_HOST,
            "/v1beta1/options/snapshots",
            api_key=api_key,
            secret_key=secret_key,
            query={"symbols": ",".join(symbols), "feed": "indicative"},
        )
        snapshots = _extract_snapshots(snapshot_payload)
    checks.append(
        _check(
            "indicative_option_snapshots",
            bool(snapshots),
            f"Indicative feed returned {len(snapshots)} snapshots from {len(symbols)} requested symbols.",
        )
    )
    greek_count = sum(bool(snapshot.get("greeks")) for snapshot in snapshots.values())
    iv_count = sum(
        snapshot.get("impliedVolatility", snapshot.get("implied_volatility")) is not None
        for snapshot in snapshots.values()
    )
    checks.append(
        _check(
            "greeks_and_iv_observed",
            greek_count > 0 and iv_count > 0,
            f"Observed Greeks on {greek_count} and IV on {iv_count} of {len(snapshots)} snapshots. "
            "Missing values are allowed by the strategy fallback.",
            critical=False,
        )
    )

    rate_headers: dict[str, str] = {}
    for source in (account_headers, clock_headers, contract_headers, snapshot_headers):
        for key, value in source.items():
            if key.startswith("x-ratelimit-") or key in {"retry-after", "x-request-id"}:
                rate_headers[key] = value

    critical_failures = [
        check["name"] for check in checks if check["critical"] and not check["passed"]
    ]
    return {
        "mode": "paper-read-only",
        "underlying": underlying,
        "account": summary,
        "clock": {
            "timestamp": clock.get("timestamp"),
            "is_open": clock.get("is_open"),
            "next_open": clock.get("next_open"),
            "next_close": clock.get("next_close"),
        },
        "contract_window": {"from": start.isoformat(), "to": end.isoformat()},
        "observed_headers": rate_headers,
        "checks": checks,
        "ready_for_order_validation": not critical_failures,
        "critical_failures": critical_failures,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--underlying", default="SPY", help="Underlying symbol to probe.")
    parser.add_argument(
        "--env-file", type=Path, default=Path(".env"), help="Optional local environment file."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional report path. Use data/private/ because this contains account metadata.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    load_local_env(args.env_file)
    if os.getenv("ALPACA_PAPER", "").strip().lower() != "true":
        print("Refusing to run: ALPACA_PAPER must be explicitly set to true.", file=sys.stderr)
        return 2
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret_key:
        print(
            "Missing paper credentials. Copy .env.example to .env and set the two Alpaca keys.",
            file=sys.stderr,
        )
        return 2
    try:
        report = run_preflight(api_key, secret_key, args.underlying.strip().upper())
    except ApiError as exc:
        print(f"Preflight failed safely: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["ready_for_order_validation"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

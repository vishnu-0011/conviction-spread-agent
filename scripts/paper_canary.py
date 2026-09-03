"""Preview and, with explicit dual approval, submit one Alpaca paper MLeg canary."""

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from conviction_spread_agent.alpaca_readonly import AlpacaReadError, AlpacaReadOnlyClient
from conviction_spread_agent.canary import CanaryPreparation, prepare_canary
from conviction_spread_agent.execution import (
    AlpacaExecutionError,
    AlpacaPaperOrderClient,
    ExecutionAuthorization,
    ExecutionBlocked,
    JsonLifecycleStore,
    PaperExecutionGateway,
)
from conviction_spread_agent.lifecycle import (
    LifecycleEvent,
    LifecycleEventType,
    apply_event,
    start_lifecycle,
)
from conviction_spread_agent.model_provider import ModelProviderError
from conviction_spread_agent.reconciliation import (
    AlpacaPaperStateClient,
    AlpacaReconciliationError,
    reconcile_flat_canary_account,
)
from shadow_scan import load_local_env, run_live_shadow


ROOT = Path(__file__).resolve().parents[1]
NEW_YORK = ZoneInfo("America/New_York")


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("shadow decision timestamp is unavailable")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("shadow decision timestamp must be timezone-aware")
    return parsed


def _session_minutes(
    now: datetime, *, market_open: bool
) -> tuple[int | None, int | None]:
    if not market_open:
        return None, None
    local_now = now.astimezone(NEW_YORK)
    session_open = datetime.combine(local_now.date(), time(9, 30), tzinfo=NEW_YORK)
    session_close = datetime.combine(local_now.date(), time(16, 0), tzinfo=NEW_YORK)
    return (
        int((local_now - session_open).total_seconds() // 60),
        int((session_close - local_now).total_seconds() // 60),
    )


def _write_record(path: Path | None, record: dict[str, object]) -> None:
    rendered = json.dumps(record, indent=2, sort_keys=True)
    print(rendered)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")


def _prepare(
    *,
    api_key: str,
    secret_key: str,
    underlying: str,
    stock_feed: str,
    option_feed: str,
    ai_provider: str,
) -> CanaryPreparation:
    shadow = run_live_shadow(
        AlpacaReadOnlyClient(api_key, secret_key),
        underlying=underlying,
        stock_feed=stock_feed,
        option_feed=option_feed,
        ai_provider=ai_provider,
        openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip() or None,
        openai_model=os.environ.get("OPENAI_MODEL", "").strip() or None,
    )
    state_client = AlpacaPaperStateClient(api_key, secret_key)
    broker = reconcile_flat_canary_account(
        state_client.account(),
        state_client.positions(),
        state_client.open_orders(),
    )
    generated_at = _timestamp(shadow.get("generated_at"))
    data = shadow.get("data")
    if not isinstance(data, dict):
        raise ValueError("shadow decision data is unavailable")
    market_open = bool(data.get("market_open"))
    minutes_since_open, minutes_until_close = _session_minutes(
        generated_at, market_open=market_open
    )
    return prepare_canary(
        shadow,
        broker,
        prepared_at=datetime.now(timezone.utc),
        minutes_since_market_open=minutes_since_open,
        minutes_until_market_close=minutes_until_close,
    )


def _submission_record(
    preparation: CanaryPreparation,
    *,
    broker_order_id: str,
    broker_status: str,
    lifecycle_state: str,
    response_sha256: str,
) -> dict[str, object]:
    record = dict(preparation.record)
    record["schema_version"] = "phase-7b.paper-canary-submission.v1"
    record["mode"] = "paper-canary-submitted"
    record["submission"] = {
        "broker_order_id": broker_order_id,
        "broker_status": broker_status,
        "lifecycle_state": lifecycle_state,
        "response_sha256": response_sha256,
    }
    safety = dict(record["safety"])  # type: ignore[arg-type]
    safety["preview_only"] = False
    safety["broker_write_performed"] = True
    safety["operator_confirmation_received"] = True
    record["safety"] = safety
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create an exact one-contract paper canary preview. Submission requires "
            "--submit, ALPACA_CANARY_SUBMISSION=true, and an interactive exact-order "
            "confirmation."
        )
    )
    parser.add_argument("--underlying", default="IWM")
    parser.add_argument("--stock-feed", default="iex")
    parser.add_argument("--option-feed", default="indicative")
    parser.add_argument(
        "--ai-provider",
        choices=("deterministic", "openai"),
        default="deterministic",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Request one paper POST after every gate and interactive confirmation.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--state-directory",
        type=Path,
        default=ROOT / "data" / "private" / "lifecycles",
    )
    args = parser.parse_args(argv)

    load_local_env(ROOT / ".env")
    if os.environ.get("ALPACA_PAPER", "").strip().lower() != "true":
        print("refusing to run: ALPACA_PAPER=true is required", file=sys.stderr)
        return 2
    api_key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret_key:
        print("missing ALPACA_API_KEY or ALPACA_SECRET_KEY", file=sys.stderr)
        return 2

    try:
        preparation = _prepare(
            api_key=api_key,
            secret_key=secret_key,
            underlying=args.underlying.strip().upper(),
            stock_feed=args.stock_feed.strip().lower(),
            option_feed=args.option_feed.strip().lower(),
            ai_provider=args.ai_provider,
        )
        _write_record(args.output, preparation.record)
        if not args.submit:
            return 0
        if not preparation.ready or preparation.intent is None or preparation.risk is None:
            print("paper canary blocked: preview is not execution-ready", file=sys.stderr)
            return 3
        execution_environment = {
            "ALPACA_CANARY_SUBMISSION": os.environ.get(
                "ALPACA_CANARY_SUBMISSION", ""
            ).strip().lower(),
            "CSA_EXECUTION_ENABLED": os.environ.get(
                "CSA_EXECUTION_ENABLED", ""
            ).strip().lower(),
            "CSA_DRY_RUN": os.environ.get("CSA_DRY_RUN", "").strip().lower(),
            "CSA_KILL_SWITCH": os.environ.get(
                "CSA_KILL_SWITCH", ""
            ).strip().lower(),
        }
        required_environment = {
            "ALPACA_CANARY_SUBMISSION": "true",
            "CSA_EXECUTION_ENABLED": "true",
            "CSA_DRY_RUN": "false",
            "CSA_KILL_SWITCH": "false",
        }
        incorrect = [
            f"{name}={required}"
            for name, required in required_environment.items()
            if execution_environment[name] != required
        ]
        if incorrect:
            print(
                "paper canary blocked: set the explicit runtime gates: "
                + ", ".join(incorrect),
                file=sys.stderr,
            )
            return 3

        expected = f"APPROVE {preparation.intent.client_order_id}"
        confirmation = input(
            "\nReview the exact legs, debit, and maximum loss above.\n"
            f"Type exactly: {expected}\n> "
        ).strip()
        if confirmation != expected:
            print("paper canary canceled: exact confirmation did not match", file=sys.stderr)
            return 4

        intent = preparation.intent
        risk = preparation.risk
        lifecycle = start_lifecycle(intent)
        lifecycle = apply_event(
            lifecycle,
            LifecycleEvent(
                event_id=f"canary-risk-{intent.payload_sha256[:20]}",
                event_type=LifecycleEventType.RISK_APPROVED,
                occurred_at=risk.assessed_at,
            ),
        )
        store = JsonLifecycleStore(args.state_directory)
        store.save(lifecycle)
        authorized_at = datetime.now(timezone.utc)
        authorization = ExecutionAuthorization(
            paper_trading=True,
            submission_enabled=True,
            dry_run=False,
            broker_reconciled=True,
            kill_switch=False,
            operator_canary_approved=True,
            maximum_contracts=1,
            valid_until=authorized_at + timedelta(seconds=60),
            client_order_id=intent.client_order_id,
            payload_sha256=intent.payload_sha256,
        )
        gateway = PaperExecutionGateway(
            AlpacaPaperOrderClient(api_key, secret_key),
            store,
            submission_enabled=True,
        )
        result = gateway.submit_entry(intent, risk, authorization, lifecycle)
        submitted = _submission_record(
            preparation,
            broker_order_id=result.broker_order_id,
            broker_status=result.broker_status.value,
            lifecycle_state=result.lifecycle.state.value,
            response_sha256=result.response_sha256,
        )
        _write_record(args.output, submitted)
        return 0
    except ExecutionBlocked as exc:
        print(f"paper canary blocked safely: {'; '.join(exc.reasons)}", file=sys.stderr)
        return 3
    except AlpacaExecutionError as exc:
        detail = (
            "submission outcome is uncertain; reconcile the client order id before "
            "any further action"
            if exc.outcome_unknown
            else "broker rejected the paper request before an order was accepted"
        )
        print(f"paper canary broker failure: {exc}; {detail}", file=sys.stderr)
        return 5
    except (AlpacaReadError, AlpacaReconciliationError, ModelProviderError, ValueError) as exc:
        print(f"paper canary failed safely: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

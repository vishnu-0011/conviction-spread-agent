"""Preview and explicitly submit one risk-reducing Alpaca paper MLeg close."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from conviction_spread_agent.alpaca_readonly import AlpacaReadError, AlpacaReadOnlyClient
from conviction_spread_agent.close import (
    ClosePreparation,
    entry_intent_from_record,
    exit_intent_from_record,
    prepare_close,
)
from conviction_spread_agent.execution import (
    AlpacaExecutionError,
    AlpacaPaperOrderClient,
    ExecutionAuthorization,
    ExecutionBlocked,
    JsonLifecycleStore,
    PaperExecutionGateway,
)
from conviction_spread_agent.lifecycle import LifecycleState
from conviction_spread_agent.reconciliation import (
    AlpacaPaperStateClient,
    AlpacaReconciliationError,
)
from shadow_scan import load_local_env


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("entry record must be a JSON object")
    return payload


def _emit(record: dict[str, object], output: Path | None) -> None:
    rendered = json.dumps(record, indent=2, sort_keys=True)
    print(rendered)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")


def _submission_record(
    preparation: ClosePreparation,
    *,
    broker_order_id: str,
    broker_status: str,
    lifecycle_state: str,
    response_sha256: str,
) -> dict[str, object]:
    record = dict(preparation.record)
    record["schema_version"] = "phase-7d.paper-close-submission.v1"
    record["mode"] = "paper-close-submitted"
    record["submission"] = {
        "broker_order_fingerprint": hashlib.sha256(
            broker_order_id.encode("utf-8")
        ).hexdigest()[:12],
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
            "Reconcile a filled one-contract entry and create an exact MLeg close "
            "preview. Submission requires --submit, explicit runtime gates, and an "
            "interactive exact-order confirmation."
        )
    )
    parser.add_argument("--entry-record", type=Path, required=True)
    parser.add_argument(
        "--exit-record",
        type=Path,
        default=None,
        help="Saved close preview/submission for GET-only exit reconciliation.",
    )
    parser.add_argument(
        "--underlying",
        default=None,
        help="Fallback only for older entry records that do not contain underlying.",
    )
    parser.add_argument("--option-feed", default="indicative")
    parser.add_argument("--submit", action="store_true")
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
        entry = entry_intent_from_record(
            _load_json(args.entry_record),
            fallback_underlying=(
                args.underlying.strip().upper() if args.underlying else None
            ),
        )
        store = JsonLifecycleStore(args.state_directory)
        lifecycle = store.load(entry.client_order_id)
        if lifecycle is None:
            raise ValueError("no durable submitted-entry lifecycle matches this record")

        order_client = AlpacaPaperOrderClient(api_key, secret_key)
        gateway = PaperExecutionGateway(
            order_client,
            store,
            submission_enabled=args.submit,
        )
        if lifecycle.exit_client_order_id is not None:
            if args.exit_record is None:
                raise ValueError(
                    "an exit is already durable; provide --exit-record for GET-only reconciliation"
                )
            saved_exit = exit_intent_from_record(
                _load_json(args.exit_record), entry_intent=entry
            )
            exit_result = gateway.reconcile_exit(saved_exit, lifecycle)
            reconciliation_record: dict[str, object] = {
                "schema_version": "phase-7d.paper-close-reconciliation.v1",
                "mode": "paper-close-reconciliation",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "entry_client_order_id": lifecycle.client_order_id,
                "exit_client_order_id": saved_exit.client_order_id,
                "broker_status": exit_result.broker_status.value,
                "consistent": exit_result.consistent,
                "reasons": list(exit_result.reasons),
                "lifecycle_state": exit_result.lifecycle.state.value,
                "active_quantity": exit_result.lifecycle.active_quantity,
                "safety": {
                    "paper_only": True,
                    "get_lookup_only": True,
                    "automatic_resubmission_prohibited": True,
                    "broker_write_performed": False,
                },
            }
            _emit(reconciliation_record, args.output)
            return 0 if exit_result.consistent else 3
        if lifecycle.state is not LifecycleState.OPEN:
            entry_result = gateway.reconcile_entry(entry, lifecycle)
            lifecycle = entry_result.lifecycle
            if not entry_result.consistent:
                raise ValueError(
                    "entry reconciliation is unresolved: "
                    + "; ".join(entry_result.reasons)
                )
        if lifecycle.state is not LifecycleState.OPEN or lifecycle.active_quantity != 1:
            raise ValueError("entry is not broker-confirmed OPEN for exactly one contract")

        read_client = AlpacaReadOnlyClient(api_key, secret_key)
        clock = read_client.clock()
        market_open = bool(clock.get("is_open"))
        spread = entry.spread
        lower_strike = min(spread.long_leg.strike, spread.short_leg.strike)
        upper_strike = max(spread.long_leg.strike, spread.short_leg.strike)
        snapshots = read_client.option_chain(
            spread.long_leg.underlying,
            right=spread.long_leg.right.value,
            expiration_from=spread.long_leg.expiration,
            expiration_to=spread.long_leg.expiration,
            strike_from=str(lower_strike),
            strike_to=str(upper_strike),
            feed=args.option_feed.strip().lower(),
        )
        state_client = AlpacaPaperStateClient(api_key, secret_key)
        preparation = prepare_close(
            entry_intent=entry,
            snapshots=snapshots,
            positions=state_client.positions(),
            market_open=market_open,
            prepared_at=datetime.now(timezone.utc),
        )
        preview = dict(preparation.record)
        preview["lifecycle"] = {
            "state": lifecycle.state.value,
            "active_quantity": lifecycle.active_quantity,
            "entry_client_order_id": lifecycle.client_order_id,
        }
        _emit(preview, args.output)
        if not args.submit:
            return 0
        if not preparation.ready or preparation.exit_intent is None:
            print("paper close blocked: preview is not execution-ready", file=sys.stderr)
            return 3

        runtime = {
            "ALPACA_CLOSE_SUBMISSION": os.environ.get(
                "ALPACA_CLOSE_SUBMISSION", ""
            ).strip().lower(),
            "CSA_EXECUTION_ENABLED": os.environ.get(
                "CSA_EXECUTION_ENABLED", ""
            ).strip().lower(),
            "CSA_DRY_RUN": os.environ.get("CSA_DRY_RUN", "").strip().lower(),
        }
        required = {
            "ALPACA_CLOSE_SUBMISSION": "true",
            "CSA_EXECUTION_ENABLED": "true",
            "CSA_DRY_RUN": "false",
        }
        incorrect = [
            f"{name}={value}"
            for name, value in required.items()
            if runtime[name] != value
        ]
        if incorrect:
            print(
                "paper close blocked: set the explicit runtime gates: "
                + ", ".join(incorrect),
                file=sys.stderr,
            )
            return 3

        exit_intent = preparation.exit_intent
        expected = f"APPROVE CLOSE {exit_intent.client_order_id}"
        confirmation = input(
            "\nReview the exact closing legs and minimum credit above.\n"
            f"Type exactly: {expected}\n> "
        ).strip()
        if confirmation != expected:
            print("paper close canceled: exact confirmation did not match", file=sys.stderr)
            return 4

        authorized_at = datetime.now(timezone.utc)
        authorization = ExecutionAuthorization(
            paper_trading=True,
            submission_enabled=True,
            dry_run=False,
            broker_reconciled=True,
            kill_switch=os.environ.get("CSA_KILL_SWITCH", "").strip().lower()
            == "true",
            operator_canary_approved=True,
            market_open=market_open,
            maximum_contracts=1,
            valid_until=authorized_at + timedelta(seconds=60),
            client_order_id=exit_intent.client_order_id,
            payload_sha256=exit_intent.payload_sha256,
        )
        result = gateway.submit_exit(exit_intent, authorization, lifecycle)
        submitted = _submission_record(
            preparation,
            broker_order_id=result.broker_order_id,
            broker_status=result.broker_status.value,
            lifecycle_state=result.lifecycle.state.value,
            response_sha256=result.response_sha256,
        )
        _emit(submitted, args.output)
        return 0
    except ExecutionBlocked as exc:
        print(f"paper close blocked safely: {'; '.join(exc.reasons)}", file=sys.stderr)
        return 3
    except AlpacaExecutionError as exc:
        detail = (
            "close outcome is uncertain; reconcile the exit client order ID"
            if exc.outcome_unknown
            else "broker rejected the paper close request"
        )
        print(f"paper close broker failure: {exc}; {detail}", file=sys.stderr)
        return 5
    except (AlpacaReadError, AlpacaReconciliationError, OSError, ValueError) as exc:
        print(f"paper close failed safely: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

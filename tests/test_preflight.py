import unittest

from decimal import Decimal

from scripts.preflight import (
    _account_summary,
    _extract_contracts,
    _extract_snapshots,
    _mask,
    _rank_contracts_near_spot,
    _spot_price,
)


class PreflightTests(unittest.TestCase):
    def test_masks_account_identifiers(self) -> None:
        self.assertEqual(_mask("ABCDEFGH1234"), "********1234")
        self.assertEqual(_mask("1234"), "****")
        self.assertIsNone(_mask(None))

    def test_account_summary_does_not_contain_full_identifiers(self) -> None:
        summary = _account_summary(
            {
                "id": "account-uuid-1234",
                "account_number": "PA123456789",
                "status": "ACTIVE",
                "options_trading_level": 3,
            }
        )
        rendered = str(summary)
        self.assertNotIn("account-uuid-1234", rendered)
        self.assertNotIn("PA123456789", rendered)
        self.assertEqual(summary["options_trading_level"], 3)

    def test_extracts_current_contract_and_snapshot_shapes(self) -> None:
        self.assertEqual(
            _extract_contracts({"option_contracts": [{"symbol": "SPY1"}]}),
            [{"symbol": "SPY1"}],
        )
        self.assertEqual(
            _extract_snapshots({"snapshots": {"SPY1": {"greeks": {"delta": 0.5}}}}),
            {"SPY1": {"greeks": {"delta": 0.5}}},
        )

    def test_extracts_underlying_price_from_current_snapshot_shape(self) -> None:
        self.assertEqual(
            _spot_price({"latestTrade": {"p": 769.13}}),
            Decimal("769.13"),
        )

    def test_ranks_only_tradable_valid_contracts_nearest_to_spot(self) -> None:
        contracts = [
            {"symbol": "FAR", "tradable": True, "strike_price": "800"},
            {"symbol": "HALTED", "tradable": False, "strike_price": "770"},
            {"symbol": "NEAR", "tradable": True, "strike_price": "771"},
            {"symbol": "INVALID", "tradable": True, "strike_price": None},
        ]
        ranked = _rank_contracts_near_spot(contracts, Decimal("769"))
        self.assertEqual([contract["symbol"] for contract in ranked], ["NEAR", "FAR"])

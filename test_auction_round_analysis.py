import tempfile
import unittest
from pathlib import Path

import pandas as pd

from auction_round_analysis import (
    aggregate_auction_binding_constraints,
    compare_round_binding_constraints,
    load_auction_binding_constraints,
    prepare_auction_constraints_for_mapping,
)


def _binding_rows(*rows):
    return pd.DataFrame(
        rows,
        columns=[
            "DeviceName",
            "DeviceType",
            "Direction",
            "Contingency",
            "MarginalCost",
            "Class",
        ],
    )


class AuctionRoundAnalysisTest(unittest.TestCase):
    def test_loads_path_list_and_aggregates_rounds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            round1 = root / "Round 1" / "Public"
            round2 = root / "Round 2" / "Public"
            round1.mkdir(parents=True)
            round2.mkdir(parents=True)

            _binding_rows(
                ("DEV  A", "Line", "From-To", "BASE", 10.0, "Peak"),
                ("DEV B", "Transformer", "To-From", "CTG1", 7.0, "Peak"),
            ).to_csv(
                round1 / "BindingConstraint_Sum26_AUCTION_Annual26Auc_Round_1.csv",
                index=False,
            )
            _binding_rows(
                (" DEV A ", "Line", "From-To", "BASE", 20.0, "Peak"),
                ("DEV C", "Flowgate", "From-To", "CTG2", 5.0, "Peak"),
            ).to_csv(
                round2 / "BindingConstraint_Sum26_AUCTION_Annual26Auc_Round_2.csv",
                index=False,
            )

            raw = load_auction_binding_constraints(
                [round1, round2],
                "Sum26",
                "AUCTION",
                "Annual26Auc",
            )
            aggregated = aggregate_auction_binding_constraints(raw)

        dev_a = aggregated.loc[aggregated["DeviceName"].eq("DEV A")].iloc[0]
        self.assertEqual(dev_a["MarginalCost"], -30.0)
        self.assertEqual(dev_a["ShadowPriceAbsTotal"], 30.0)
        self.assertEqual(dev_a["Rank"], 1)
        self.assertEqual(dev_a["DA"], "False")
        self.assertEqual(dev_a["AuctionRounds"], "1,2")

    def test_compare_rounds_labels_new_missing_and_changes(self):
        raw = pd.DataFrame(
            [
                ["DEV A", "Line", "From-To", "BASE", -10.0, "Peak", 1],
                ["DEV B", "Line", "From-To", "BASE", -7.0, "Peak", 1],
                ["DEV A", "Line", "From-To", "BASE", -12.5, "Peak", 2],
                ["DEV C", "Line", "From-To", "BASE", -5.0, "Peak", 2],
            ],
            columns=[
                "DeviceName",
                "DeviceType",
                "Direction",
                "Contingency",
                "AuctionShadowPrice",
                "Class",
                "AuctionRound",
            ],
        )

        comparison = compare_round_binding_constraints(raw)
        by_device = comparison.set_index("DeviceName")

        self.assertEqual(by_device.loc["DEV A", "Round2Status"], "Present in both rounds")
        self.assertEqual(by_device.loc["DEV A", "ShadowPriceChange"], -2.5)
        self.assertEqual(by_device.loc["DEV B", "Round2Status"], "Missing from Round 2")
        self.assertEqual(by_device.loc["DEV B", "ShadowPriceChange"], 7.0)
        self.assertEqual(by_device.loc["DEV C", "Round2Status"], "New in Round 2")
        self.assertEqual(by_device.loc["DEV C", "ShadowPriceChange"], -5.0)

    def test_prepare_returns_mapping_comparison_and_raw_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            public_dir = Path(tmpdir) / "Round 1" / "Public"
            public_dir.mkdir(parents=True)
            _binding_rows(
                ("DEV A", "Line", "From-To", "BASE", 10.0, "Peak"),
            ).to_csv(
                public_dir / "BindingConstraint_Sum26_AUCTION_Annual26Auc_Round_1.csv",
                index=False,
            )

            aggregated, comparison, raw = prepare_auction_constraints_for_mapping(
                public_dir,
                "Sum26",
                "AUCTION",
                "Annual26Auc",
            )

        self.assertEqual(len(raw), 1)
        self.assertEqual(len(aggregated), 1)
        self.assertEqual(len(comparison), 1)


if __name__ == "__main__":
    unittest.main()

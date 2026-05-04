r"""Helpers for multi-round annual auction binding-constraint analysis.

The functions in this module are intentionally independent from PowerWorld so
they can be used before calling the existing ``map_auction_constraint`` step.
They preserve the single-round behavior while also accepting:

    auction_result_path = [
        r"G:\Power\MISO\FTR Results\2026_00\Round 1\Public",
        r"G:\Power\MISO\FTR Results\2026_00\Round 2\Public",
    ]

The main entry point is ``prepare_auction_constraints_for_mapping``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd


AUCTION_KEY_COLUMNS = ["DeviceName", "DeviceType", "Direction", "Contingency"]
REQUIRED_BINDING_COLUMNS = AUCTION_KEY_COLUMNS + ["MarginalCost", "Class"]


def _as_list(value: str | os.PathLike[str] | Sequence[str | os.PathLike[str]]) -> list[str]:
    """Return a path or path-like sequence as a plain list of strings."""
    if isinstance(value, (str, os.PathLike)):
        return [os.fspath(value)]
    return [os.fspath(item) for item in value]


def _normalize_name(value: object) -> str:
    """Match the existing auction constraint normalization."""
    if pd.isna(value):
        return ""
    return " ".join(str(value).strip().split())


def _infer_round_from_path(path: str, fallback: int) -> int:
    """Infer ``Round 1`` / ``Round_1`` / ``Round-1`` from a result folder path."""
    match = re.search(r"round[\s_-]*(\d+)", path, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return fallback


def _binding_constraint_file(
    auction_result_dir: str,
    tou_str: str,
    auction_type: str,
    auction_name: str,
    auction_round: int,
) -> str:
    filename = (
        f"BindingConstraint_{tou_str}_{auction_type}_{auction_name}_"
        f"Round_{auction_round}.csv"
    )
    return os.path.join(auction_result_dir, filename)


def load_auction_binding_constraints(
    auction_result_path: str | os.PathLike[str] | Sequence[str | os.PathLike[str]],
    tou_str: str,
    auction_type: str,
    auction_name: str,
    auction_rounds: Sequence[int] | None = None,
) -> pd.DataFrame:
    """Load binding constraints from one or more auction result folders.

    Parameters
    ----------
    auction_result_path:
        Either the legacy single Public-folder path or a list of Public-folder
        paths, one per round.
    tou_str, auction_type, auction_name:
        Existing filename components used by MISO auction result exports.
    auction_rounds:
        Optional explicit round numbers. When omitted, round numbers are parsed
        from each path's ``Round N`` segment, falling back to list order.

    Returns
    -------
    pandas.DataFrame
        Raw binding constraints with normalized device names, ``AuctionRound``,
        ``AuctionFile``, and ``AuctionShadowPrice`` columns. Shadow price uses
        the existing convention from the annual auction script: negative
        absolute marginal cost.
    """
    result_dirs = _as_list(auction_result_path)
    if auction_rounds is not None and len(auction_rounds) != len(result_dirs):
        raise ValueError("auction_rounds must have the same length as auction_result_path")

    frames: list[pd.DataFrame] = []
    missing_files: list[str] = []

    for index, result_dir in enumerate(result_dirs, start=1):
        round_no = (
            int(auction_rounds[index - 1])
            if auction_rounds is not None
            else _infer_round_from_path(result_dir, index)
        )
        binding_file = _binding_constraint_file(
            result_dir, tou_str, auction_type, auction_name, round_no
        )
        if not os.path.exists(binding_file):
            missing_files.append(binding_file)
            continue

        frame = pd.read_csv(binding_file)
        missing_columns = set(REQUIRED_BINDING_COLUMNS) - set(frame.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"{binding_file} is missing required columns: {missing}")

        frame = frame.copy()
        frame["DeviceName"] = frame["DeviceName"].map(_normalize_name)
        frame["Contingency"] = frame["Contingency"].map(_normalize_name)
        frame["AuctionRound"] = round_no
        frame["AuctionFile"] = binding_file
        frame["AuctionShadowPrice"] = -pd.to_numeric(
            frame["MarginalCost"], errors="coerce"
        ).abs()
        frames.append(frame)

    if missing_files:
        missing = "\n".join(f"  - {file}" for file in missing_files)
        raise FileNotFoundError(f"BindingConstraint files were not found:\n{missing}")

    if not frames:
        return pd.DataFrame(columns=REQUIRED_BINDING_COLUMNS + ["AuctionRound"])

    return pd.concat(frames, ignore_index=True)


def aggregate_auction_binding_constraints(auction_constraints: pd.DataFrame) -> pd.DataFrame:
    """Aggregate binding constraints across all loaded rounds for mapping.

    The output can be passed directly to the existing ``map_auction_constraint``
    function. ``MarginalCost`` is the sum of round shadow prices, ``DA`` is
    labelled ``False``, and ``Rank`` is based on total absolute shadow price
    across the included rounds.
    """
    if auction_constraints.empty:
        return pd.DataFrame(
            columns=REQUIRED_BINDING_COLUMNS
            + ["DA", "Rank", "ShadowPriceAbsTotal", "AuctionRounds"]
        )

    work = auction_constraints.copy()
    work["AuctionShadowPrice"] = pd.to_numeric(
        work["AuctionShadowPrice"], errors="coerce"
    ).fillna(0.0)
    work["ShadowPriceAbs"] = work["AuctionShadowPrice"].abs()

    grouped = (
        work.groupby(AUCTION_KEY_COLUMNS, as_index=False, dropna=False)
        .agg(
            MarginalCost=("AuctionShadowPrice", "sum"),
            ShadowPriceAbsTotal=("ShadowPriceAbs", "sum"),
            Class=("Class", "first"),
            AuctionRounds=("AuctionRound", lambda s: ",".join(map(str, sorted(set(s))))),
        )
        .sort_values(["ShadowPriceAbsTotal", "MarginalCost"], ascending=[False, True])
        .reset_index(drop=True)
    )
    grouped["Rank"] = grouped["ShadowPriceAbsTotal"].rank(
        method="dense", ascending=False
    ).astype("int64")
    grouped["DA"] = "False"
    return grouped[
        REQUIRED_BINDING_COLUMNS
        + ["DA", "Rank", "ShadowPriceAbsTotal", "AuctionRounds"]
    ]


def compare_round_binding_constraints(
    auction_constraints: pd.DataFrame,
    round_1: int = 1,
    round_2: int = 2,
) -> pd.DataFrame:
    """Compare Round 2 binding constraints against Round 1.

    The returned table includes constraints that are present in both rounds,
    new in Round 2, and missing from Round 2. ``ShadowPriceChange`` is
    Round 2 minus Round 1, using the same negative shadow-price convention as
    the existing annual auction workflow.
    """
    if auction_constraints.empty:
        return pd.DataFrame(
            columns=AUCTION_KEY_COLUMNS
            + [
                "Round1ShadowPrice",
                "Round2ShadowPrice",
                "ShadowPriceChange",
                "Round2Status",
            ]
        )

    work = auction_constraints.copy()
    work = work[work["AuctionRound"].isin([round_1, round_2])].copy()
    work["AuctionShadowPrice"] = pd.to_numeric(
        work["AuctionShadowPrice"], errors="coerce"
    ).fillna(0.0)

    by_round = (
        work.groupby(AUCTION_KEY_COLUMNS + ["AuctionRound"], as_index=False, dropna=False)
        .agg(
            ShadowPrice=("AuctionShadowPrice", "sum"),
            Class=("Class", "first"),
        )
    )

    comparison = by_round.pivot_table(
        index=AUCTION_KEY_COLUMNS,
        columns="AuctionRound",
        values="ShadowPrice",
        aggfunc="sum",
        dropna=False,
    ).reset_index()
    comparison = comparison.rename(
        columns={
            round_1: "Round1ShadowPrice",
            round_2: "Round2ShadowPrice",
        }
    )

    for column in ["Round1ShadowPrice", "Round2ShadowPrice"]:
        if column not in comparison.columns:
            comparison[column] = pd.NA

    comparison["Round2Status"] = "Present in both rounds"
    comparison.loc[comparison["Round1ShadowPrice"].isna(), "Round2Status"] = (
        "New in Round 2"
    )
    comparison.loc[comparison["Round2ShadowPrice"].isna(), "Round2Status"] = (
        "Missing from Round 2"
    )
    comparison["ShadowPriceChange"] = (
        comparison["Round2ShadowPrice"].fillna(0.0)
        - comparison["Round1ShadowPrice"].fillna(0.0)
    )

    class_lookup = (
        by_round.sort_values("AuctionRound")
        .drop_duplicates(AUCTION_KEY_COLUMNS, keep="last")[AUCTION_KEY_COLUMNS + ["Class"]]
    )
    comparison = comparison.merge(class_lookup, on=AUCTION_KEY_COLUMNS, how="left")
    comparison["Round1AbsShadowPrice"] = comparison["Round1ShadowPrice"].abs()
    comparison["Round2AbsShadowPrice"] = comparison["Round2ShadowPrice"].abs()

    return comparison[
        AUCTION_KEY_COLUMNS
        + [
            "Class",
            "Round1ShadowPrice",
            "Round2ShadowPrice",
            "ShadowPriceChange",
            "Round1AbsShadowPrice",
            "Round2AbsShadowPrice",
            "Round2Status",
        ]
    ].sort_values(
        ["Round2Status", "Round2AbsShadowPrice", "Round1AbsShadowPrice"],
        ascending=[True, False, False],
        na_position="last",
    )


def prepare_auction_constraints_for_mapping(
    auction_result_path: str | os.PathLike[str] | Sequence[str | os.PathLike[str]],
    tou_str: str,
    auction_type: str,
    auction_name: str,
    auction_rounds: Sequence[int] | None = None,
    comparison_rounds: tuple[int, int] = (1, 2),
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load, aggregate, and compare previous auction binding constraints.

    Returns
    -------
    tuple[pandas.DataFrame, pandas.DataFrame, pandas.DataFrame]
        ``(auction_constraints_for_mapping, round_comparison, raw_constraints)``.

    Example
    -------
    Replace the legacy single-round block with:

    >>> auction_constraints_for_mapping, round_comparison, raw_constraints = (
    ...     prepare_auction_constraints_for_mapping(
    ...         auction_result_path,
    ...         tou_str,
    ...         auction_type,
    ...         auction_name,
    ...     )
    ... )
    >>> auction_constraints_mapped, auction_monitor_ele = map_auction_constraint(
    ...     auction_constraints_for_mapping,
    ...     ftr_ctg_aux_mapped,
    ...     nomg,
    ...     flowgates,
    ...     BranchList_ftr,
    ... )
    """
    raw_constraints = load_auction_binding_constraints(
        auction_result_path=auction_result_path,
        tou_str=tou_str,
        auction_type=auction_type,
        auction_name=auction_name,
        auction_rounds=auction_rounds,
    )
    aggregated_constraints = aggregate_auction_binding_constraints(raw_constraints)
    comparison = compare_round_binding_constraints(
        raw_constraints,
        round_1=comparison_rounds[0],
        round_2=comparison_rounds[1],
    )
    return aggregated_constraints, comparison, raw_constraints


def write_round_comparison_outputs(
    round_comparison: pd.DataFrame,
    output_dir: str | os.PathLike[str],
    tou_str: str,
) -> None:
    """Write Round 1 vs Round 2 comparison tables as CSV and feather files."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    round_comparison.to_csv(output_path / f"{tou_str}_round1_round2_comparison.csv", index=False)
    round_comparison.to_feather(output_path / f"{tou_str}_round1_round2_comparison.feather")

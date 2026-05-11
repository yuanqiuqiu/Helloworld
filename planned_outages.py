"""Find planned outage XML snapshots and map outage rows to BranchList."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from miso_model_mapper import QuarterModel, find_quarter_model, format_path_for_output, parse_se_datetime


DEFAULT_PLANNED_OUTAGE_ROOT = r"G:\Power\MISO\Planned Outages"

PLANNED_OUTAGE_RE = re.compile(
    r"^2308_Planned_Outages_(?P<stamp>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})\.xml$",
    re.IGNORECASE,
)

COLUMN_NAMES = {
    "OUTAGE_REQUEST_ID": "Outage_Request_ID",
    "FROM_STATION": "From_Station",
    "TO_STATION": "To_Station",
    "EMS_EQUIPMENT_NAME": "EMS_Equipment_Name",
    "EMS_KEY": "EMS_Key",
    "PLANNED_START": "Planned_Start",
    "PLANNED_END": "Planned_End",
    "ACTUAL_START": "Actual_Start",
    "ACTUAL_END": "Actual_End",
    "PRIORITY": "Priority",
    "EQUIPMENT_REQUEST_TYPE": "Equipment_Request_Type",
    "EQUIPMENT_TYPE": "Equipment_Type",
    "KV": "KV",
}

DATE_COLUMNS = ["Planned_Start", "Planned_End", "Actual_Start", "Actual_End"]


@dataclass(frozen=True)
class PlannedOutageFile:
    path: Path
    timestamp: datetime


@dataclass(frozen=True)
class SeRawInputs:
    se_raw_file: Path
    quarter_model: QuarterModel
    planned_outage_file: Path


def parse_planned_outage_timestamp(path: str | Path) -> datetime:
    """Parse timestamp from 2308_Planned_Outages_YYYY-MM-DD-HH-MM-SS.xml."""

    file_name = re.split(r"[\\/]", str(path))[-1]
    match = PLANNED_OUTAGE_RE.match(file_name)
    if not match:
        raise ValueError(f"Not a planned outage filename: {path!r}")
    return datetime.strptime(match.group("stamp"), "%Y-%m-%d-%H-%M-%S")


def planned_outage_hour_for_se_time(se_time: datetime, hour_offset: int = 4) -> int:
    """Return planned-outage filename hour. Default follows the examples: SE hour + 4."""

    return (se_time + timedelta(hours=hour_offset)).hour


def find_planned_outage_file(
    se_raw_file: str | Path,
    planned_outage_root: str | Path = DEFAULT_PLANNED_OUTAGE_ROOT,
    *,
    hour_offset: int = 4,
    require_active_outage: bool = False,
) -> Path:
    """Find the latest planned outage XML with filename hour matching the SE case."""

    se_time = parse_se_datetime(se_raw_file)
    adjusted_se_time = se_time + timedelta(hours=hour_offset)
    target_hour = adjusted_se_time.hour

    matches = []
    for path in Path(planned_outage_root).glob("**/2308_Planned_Outages_*.xml"):
        if not path.is_file():
            continue
        try:
            outage_time = parse_planned_outage_timestamp(path)
        except ValueError:
            continue
        if outage_time.hour == target_hour and outage_time <= adjusted_se_time:
            matches.append(PlannedOutageFile(path, outage_time))

    if require_active_outage:
        matches = [item for item in matches if not active_oos_outages(item.path, se_time).empty]

    if not matches:
        raise FileNotFoundError(f"No planned outage XML found for {se_raw_file} with filename hour {target_hour:02d}")
    return max(matches, key=lambda item: item.timestamp).path


def find_inputs_for_se_raw(
    se_raw_file: str | Path,
    quarter_model_root: str | Path,
    planned_outage_root: str | Path = DEFAULT_PLANNED_OUTAGE_ROOT,
    *,
    hour_offset: int = 4,
) -> SeRawInputs:
    """Find quarter model and planned outage XML for one SE raw file."""

    se_time = parse_se_datetime(se_raw_file)
    return SeRawInputs(
        se_raw_file=Path(se_raw_file),
        quarter_model=find_quarter_model(se_time.date(), quarter_model_root),
        planned_outage_file=find_planned_outage_file(se_raw_file, planned_outage_root, hour_offset=hour_offset),
    )


def read_planned_outage_xml(xml_file: str | Path) -> pd.DataFrame:
    """Read planned outage XML with pandas and normalize common column names."""

    outages = pd.read_xml(xml_file, parser="etree")
    outages.rename(columns={col: COLUMN_NAMES.get(str(col).upper(), col) for col in outages.columns}, inplace=True)
    return outages


def active_oos_outages(xml_file: str | Path, se_time: datetime) -> pd.DataFrame:
    """Read XML and return active OOS outage rows for the SE case time."""

    outages = read_planned_outage_xml(xml_file)
    if outages.empty:
        return outages

    for col in DATE_COLUMNS:
        if col not in outages.columns:
            outages[col] = pd.NaT
        outages[col] = pd.to_datetime(outages[col], errors="coerce")

    if "Equipment_Request_Type" not in outages.columns:
        return outages.iloc[0:0].copy()
    outages = outages[outages["Equipment_Request_Type"].astype(str).str.strip().str.upper() == "OOS"].copy()
    outages["start_time"] = outages["Actual_Start"].fillna(outages["Planned_Start"])
    outages["end_time"] = outages["Actual_End"].fillna(outages["Planned_End"])

    return outages[(outages["start_time"] <= se_time) & (outages["end_time"] >= se_time)].copy()


def add_ems_name(outages: pd.DataFrame) -> pd.DataFrame:
    """Add EMSName using the same rule as the existing outage mapping code."""

    outages = outages.copy()
    line_mask = outages["Equipment_Type"].astype(str).str.strip() == "Line"
    outages["EMSName"] = (
        outages["From_Station"].fillna("").astype(str).str.strip()
        + " "
        + outages["EMS_Equipment_Name"].fillna("").astype(str).str.strip()
    ).str.split().str.join(" ")
    outages.loc[line_mask, "EMSName"] = (
        outages.loc[line_mask, "EMS_Equipment_Name"].fillna("").astype(str).str.strip()
        + " "
        + outages.loc[line_mask, "EMS_Key"].fillna("").astype(str).str.strip()
    ).str.split().str.join(" ")
    return outages


def anyplace_score(a: object, b: object, w_block: float = 0.6, w_contain: float = 0.4, w_tok: float = 0.6, w_num: float = 1.0) -> float:
    """Score two EMS names for fuzzy fallback matching."""

    if not isinstance(a, str) or not isinstance(b, str):
        return 0.0
    token_pat = re.compile(r"[A-Za-z]+|\d+")
    sm = SequenceMatcher(None, a, b)
    max_block = max(m.size for m in sm.get_matching_blocks())
    block_bonus = max_block / max(len(a), len(b))
    contain_bonus = 1.0 if (a in b or b in a) else 0.0

    sa, sb = set(token_pat.findall(a)), set(token_pat.findall(b))
    tok_jacc = (len(sa & sb) / len(sa | sb)) if (sa or sb) else 0.0

    nums_a, nums_b = set(re.findall(r"\d+", a)), set(re.findall(r"\d+", b))
    digit_hit = sum(ch.isdigit() and ch in b for ch in a)
    num_bonus = (len(nums_a & nums_b) / max(1, len(nums_a))) if nums_a else float(digit_hit > 0)

    return sm.ratio() + w_block * block_bonus + w_contain * contain_bonus + w_tok * tok_jacc + w_num * num_bonus


def mapping_branch(outages: pd.DataFrame, branch_list: pd.DataFrame) -> pd.DataFrame:
    """Map outage rows to a PowerWorld BranchList dataframe."""

    if outages.empty:
        return outages.copy()

    outages = add_ems_name(outages)
    branch_cols = [
        "FromEMSName",
        "FromBusKV",
        "ToEMSName",
        "ToBusKV",
        "Circuit",
        "EMSName",
        "FromBusNum",
        "ToBusNum",
        "Status",
    ]
    outages = outages.merge(branch_list[branch_cols], how="left", on="EMSName")

    unmapped = outages["FromBusNum"].isna()
    if not unmapped.any():
        return outages

    temp = outages.loc[unmapped, ["From_Station", "To_Station", "KV", "EMSName", "Equipment_Type"]].copy()
    temp["rowid"] = temp.index
    temp["To_Station"] = temp["To_Station"].fillna(temp["From_Station"])
    temp["KV"] = temp["KV"].astype(float).round(1)

    branch_double = pd.concat([branch_list, reverse_branch_list(branch_list)], ignore_index=True)
    branch_double.loc[branch_double["Type"] == "Transformer", "ToEMSName"] = branch_double.loc[
        branch_double["Type"] == "Transformer", "FromEMSName"
    ]
    branch_double["KV"] = branch_double[["FromBusKV", "ToBusKV"]].max(axis=1).astype(float).round(1)

    temp_mapped = temp.merge(
        branch_double[
            [
                "EMSName",
                "Type",
                "FromEMSName",
                "FromBusNum",
                "FromBusKV",
                "ToEMSName",
                "ToBusNum",
                "ToBusKV",
                "KV",
                "Circuit",
            ]
        ],
        left_on=["From_Station", "To_Station", "KV", "Equipment_Type"],
        right_on=["FromEMSName", "ToEMSName", "KV", "Type"],
        how="left",
    )
    temp_mapped["score"] = temp_mapped.apply(
        lambda row: anyplace_score(row["EMSName_x"], row["EMSName_y"]) if pd.notna(row["EMSName_y"]) else 0,
        axis=1,
    )
    temp_mapped.sort_values(["rowid", "score"], ascending=[True, False], inplace=True)
    temp_mapped.drop_duplicates("rowid", keep="first", inplace=True)
    temp_mapped = temp_mapped.set_index("rowid").reindex(temp["rowid"])
    temp_mapped.rename(columns={"EMSName_y": "EMSName"}, inplace=True)

    cols_fill = ["EMSName", "FromEMSName", "FromBusKV", "ToEMSName", "ToBusKV", "Circuit", "FromBusNum", "ToBusNum"]
    cols_fill = [col for col in cols_fill if col in temp_mapped.columns and col in outages.columns]
    outages.loc[unmapped, cols_fill] = temp_mapped[cols_fill].values
    return outages.loc[outages["FromBusNum"].notna()].copy()


def map_outage_file_to_branch_lists(
    xml_file: str | Path,
    se_raw_file: str | Path,
    quarter_branch_list: pd.DataFrame,
    se_branch_list: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Read one XML outage file and map active OOS outages to both BranchLists."""

    active = active_oos_outages(xml_file, parse_se_datetime(se_raw_file))
    return {
        "quarter": mapping_branch(active, quarter_branch_list),
        "se": mapping_branch(active, se_branch_list),
        "future_retired": find_future_equipment_retired_lines(active, quarter_branch_list),
    }


def find_future_equipment_retired_lines(active: pd.DataFrame, quarter_branch_list: pd.DataFrame) -> pd.DataFrame:
    """Find original A-B branches retired by Future Equipment A-C/C-B outages."""

    if active.empty or "Priority" not in active.columns:
        return quarter_branch_list.iloc[0:0].copy()

    future = active[active["Priority"].astype(str).str.strip().str.upper() == "FUTURE EQUIPMENT"].copy()
    if future.empty:
        return quarter_branch_list.iloc[0:0].copy()

    future["group_key"] = future["Outage_Request_ID"].fillna("").astype(str).str.strip()
    missing_group = future["group_key"] == ""
    future.loc[missing_group, "group_key"] = future.loc[missing_group].apply(
        lambda row: "|".join(str(row.get(col, "")).strip() for col in ["Planned_Start", "Planned_End", "Priority", "KV"]),
        axis=1,
    )

    branch_double = pd.concat([quarter_branch_list, reverse_branch_list(quarter_branch_list)], ignore_index=True)
    branch_double["KV"] = branch_double[["FromBusKV", "ToBusKV"]].max(axis=1).astype(float).round(1)

    retired_rows = []
    for _, group in future.groupby("group_key"):
        stations = pd.Series(
            list(group["From_Station"].dropna().astype(str).str.strip())
            + list(group["To_Station"].dropna().astype(str).str.strip())
        )
        station_counts = stations[stations != ""].value_counts()
        if len(station_counts) < 3:
            continue

        center_station = station_counts.index[0]
        end_stations = [station for station in station_counts.index if station != center_station][:2]
        if len(end_stations) != 2:
            continue

        retired = branch_double[
            branch_double["FromEMSName"].isin(end_stations) & branch_double["ToEMSName"].isin(end_stations)
        ]
        if not group["KV"].dropna().empty:
            kv = round(float(group["KV"].dropna().iloc[0]), 1)
            retired = retired[retired["KV"].astype(float).round(1) == kv]
        retired_rows.append(retired)

    if not retired_rows:
        return quarter_branch_list.iloc[0:0].copy()
    return pd.concat(retired_rows, ignore_index=True).drop_duplicates()


def reverse_branch_list(branch_list: pd.DataFrame) -> pd.DataFrame:
    """Reverse From/To columns so station matching works in either direction."""

    return branch_list.rename(
        columns={
            "FromBusNum": "ToBusNum",
            "ToBusNum": "FromBusNum",
            "FromEMSName": "ToEMSName",
            "ToEMSName": "FromEMSName",
            "FromBusKV": "ToBusKV",
            "ToBusKV": "FromBusKV",
        }
    )


def print_planned_outage_match(se_raw_file: str | Path, outage_file: str | Path) -> None:
    print(f"SE raw file: {format_path_for_output(se_raw_file)}")
    print(f"Planned outage XML: {format_path_for_output(outage_file)}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find the planned outage XML for one MISO SE raw file.")
    parser.add_argument("--se-file", required=True)
    parser.add_argument("--planned-outage-root", default=DEFAULT_PLANNED_OUTAGE_ROOT)
    parser.add_argument("--hour-offset", type=int, default=4)
    parser.add_argument("--require-active-outage", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        outage_file = find_planned_outage_file(
            args.se_file,
            args.planned_outage_root,
            hour_offset=args.hour_offset,
            require_active_outage=args.require_active_outage,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    print_planned_outage_match(args.se_file, outage_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

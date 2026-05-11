"""Find planned outage XML snapshots and map outages to PowerWorld BranchList.

This module keeps the step-2 outage work separate from the simple path mapper.
PowerWorld and pandas are only needed after you have loaded cases and built the
Quarterly/SE BranchList dataframes.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from miso_model_mapper import QuarterModel, find_quarter_model, format_path_for_output, parse_se_datetime


DEFAULT_PLANNED_OUTAGE_ROOT = r"G:\Power\MISO\Planned Outages"
PLANNED_OUTAGE_RE = re.compile(
    r"^2308_Planned_Outages_(?P<stamp>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})\.xml$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PlannedOutageFile:
    path: Path
    timestamp: datetime


@dataclass(frozen=True)
class SeRawInputs:
    se_raw_file: Path
    quarter_model: QuarterModel
    planned_outage_file: Path


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
        planned_outage_file=find_planned_outage_file(
            se_raw_file,
            planned_outage_root,
            hour_offset=hour_offset,
        ),
    )


def parse_planned_outage_timestamp(path: str | Path) -> datetime:
    """Parse timestamp from a planned outage XML filename."""

    file_name = re.split(r"[\\/]", str(path))[-1]
    match = PLANNED_OUTAGE_RE.match(file_name)
    if not match:
        raise ValueError(f"Not a planned outage filename: {path!r}")
    return datetime.strptime(match.group("stamp"), "%Y-%m-%d-%H-%M-%S")


def planned_outage_hour_for_se_time(se_time: datetime, hour_offset: int = 4) -> int:
    """Return the planned-outage filename hour that matches a SE case time.

    The examples use planned-outage file hour = SE hour + 4.  If a dataset needs
    standard UTC+5 behavior instead, pass ``hour_offset=5``.
    """

    return (se_time + timedelta(hours=hour_offset)).hour


def iter_planned_outage_files(planned_outage_root: str | Path, recursive: bool = True) -> Iterable[PlannedOutageFile]:
    """Yield planned outage XML files under a folder."""

    root = Path(planned_outage_root)
    pattern = "**/2308_Planned_Outages_*.xml" if recursive else "2308_Planned_Outages_*.xml"
    for path in root.glob(pattern):
        if not path.is_file():
            continue
        try:
            yield PlannedOutageFile(path=path, timestamp=parse_planned_outage_timestamp(path))
        except ValueError:
            continue


def find_planned_outage_file(
    se_raw_file: str | Path,
    planned_outage_root: str | Path = DEFAULT_PLANNED_OUTAGE_ROOT,
    *,
    hour_offset: int = 4,
    require_active_outage: bool = False,
    recursive: bool = True,
) -> Path:
    """Find the planned outage XML snapshot associated with one SE raw file.

    The filename hour must equal SE hour + ``hour_offset``.  Because planned
    outage snapshots are published before the SE operating date, this chooses
    the latest matching-hour file whose timestamp is not after the adjusted SE
    timestamp.  Set ``require_active_outage=True`` to also require the XML to
    contain at least one outage active at the SE time.
    """

    se_time = parse_se_datetime(se_raw_file)
    adjusted_se_time = se_time + timedelta(hours=hour_offset)
    target_hour = adjusted_se_time.hour

    matches = [
        item
        for item in iter_planned_outage_files(planned_outage_root, recursive=recursive)
        if item.timestamp.hour == target_hour and item.timestamp <= adjusted_se_time
    ]
    if require_active_outage:
        matches = [item for item in matches if has_active_outage(item.path, se_time)]

    if not matches:
        raise FileNotFoundError(
            f"No planned outage XML found for {se_raw_file} with filename hour {target_hour:02d}"
        )
    return max(matches, key=lambda item: item.timestamp).path


def _clean_key(value: str) -> str:
    value = value.split("}", 1)[-1]  # remove XML namespace
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")


def _canonical_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", value).upper()


KEY_ALIASES = {
    "OUTAGEREQUESTID": "Outage_Request_ID",
    "COMPANY": "Company",
    "KV": "KV",
    "FROMSTATION": "From_Station",
    "TOSTATION": "To_Station",
    "IDCEQUIPMENTNAME": "IDC_Equipment_Name",
    "EMSEQUIPMENTNAME": "EMS_Equipment_Name",
    "EMSKEY": "EMS_Key",
    "PLANNEDSTART": "Planned_Start",
    "PLANNEDEND": "Planned_End",
    "REQUESTSTATUS": "Request_Status",
    "ACTUALSTART": "Actual_Start",
    "ACTUALEND": "Actual_End",
    "PRIORITY": "Priority",
    "EQUIPMENTREQUESTTYPE": "Equipment_Request_Type",
    "NOTES": "Notes",
    "EQUIPMENTTYPE": "Equipment_Type",
    "COMMONNAME": "Common_Name",
    "FROMCA": "From_CA",
    "TOCA": "To_CA",
    "REQUESTDATE": "Request_Date",
    "PUBLISHDATE": "Publish_Date",
}


def _normalize_record(record: dict[str, str]) -> dict[str, str]:
    normalized = {}
    for key, value in record.items():
        alias = KEY_ALIASES.get(_canonical_key(key), _clean_key(key))
        normalized[alias] = value.strip() if isinstance(value, str) else value
    return normalized


def read_planned_outage_xml(xml_file: str | Path) -> list[dict[str, str]]:
    """Read planned outage XML into a list of dictionaries.

    The XML exports can vary slightly, so this reads any element that looks like
    a row: attributes and direct child text are collected and normalized to the
    column names used by the BranchList mapping code.
    """

    root = ET.parse(xml_file).getroot()
    rows: list[dict[str, str]] = []
    known_keys = set(KEY_ALIASES.values())

    for element in root.iter():
        row: dict[str, str] = {_clean_key(key): value for key, value in element.attrib.items()}
        for child in list(element):
            if list(child):
                continue
            text = child.text.strip() if child.text else ""
            if text:
                row[_clean_key(child.tag)] = text

        normalized = _normalize_record(row)
        if len(normalized) >= 2 and known_keys.intersection(normalized):
            rows.append(normalized)

    return rows


def parse_outage_datetime(value: object) -> datetime | None:
    """Parse common planned outage date/time strings."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%m-%d-%Y %H:%M:%S",
        "%m-%d-%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m.%d.%Y %H:%M:%S",
        "%m.%d.%Y %H:%M",
        "%Y-%m-%d",
        "%m/%d/%Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def outage_start_end(record: dict[str, object]) -> tuple[datetime | None, datetime | None]:
    """Return effective outage start/end, using actual times when available."""

    start_time = parse_outage_datetime(record.get("Actual_Start")) or parse_outage_datetime(record.get("Planned_Start"))
    end_time = parse_outage_datetime(record.get("Actual_End")) or parse_outage_datetime(record.get("Planned_End"))
    return start_time, end_time


def outage_is_active(record: dict[str, object], case_time: datetime) -> bool:
    """True when an outage overlaps the SE case time."""

    start_time, end_time = outage_start_end(record)
    if start_time is None or end_time is None:
        return False
    return start_time <= case_time <= end_time


def active_oos_outages(records: Iterable[dict[str, object]], case_time: datetime) -> list[dict[str, object]]:
    """Keep active OOS outage rows for the SE case time."""

    active = []
    for record in records:
        request_type = str(record.get("Equipment_Request_Type", "")).strip().upper()
        if request_type != "OOS":
            continue
        if outage_is_active(record, case_time):
            active.append(record)
    return active


def has_active_outage(xml_file: str | Path, case_time: datetime) -> bool:
    """Return True when the XML contains any active OOS outage at case_time."""

    try:
        return bool(active_oos_outages(read_planned_outage_xml(xml_file), case_time))
    except ET.ParseError:
        return False


def add_ems_name(record: dict[str, object]) -> dict[str, object]:
    """Add EMSName using the same rule as the existing outage mapping code."""

    result = dict(record)
    equipment_type = str(result.get("Equipment_Type", "")).strip()
    if equipment_type == "Line":
        result["EMSName"] = f"{result.get('EMS_Equipment_Name', '')} {result.get('EMS_Key', '')}".strip()
    else:
        result["EMSName"] = f"{result.get('From_Station', '')} {result.get('EMS_Equipment_Name', '')}".strip()
    result["EMSName"] = " ".join(result["EMSName"].split())
    return result


def anyplace_score(a: object, b: object, w_block: float = 0.6, w_contain: float = 0.4, w_tok: float = 0.6, w_num: float = 1.0) -> float:
    """Score two EMS names for fuzzy fallback matching."""

    if not isinstance(a, str) or not isinstance(b, str):
        return 0.0
    token_pat = re.compile(r"[A-Za-z]+|\d+")
    sm = SequenceMatcher(None, a, b)
    base = sm.ratio()
    max_block = max(m.size for m in sm.get_matching_blocks())
    block_bonus = max_block / max(len(a), len(b))
    contain_bonus = 1.0 if (a in b or b in a) else 0.0

    ta, tb = token_pat.findall(a), token_pat.findall(b)
    sa, sb = set(ta), set(tb)
    tok_jacc = (len(sa & sb) / len(sa | sb)) if (sa or sb) else 0.0

    nums_a, nums_b = set(re.findall(r"\d+", a)), set(re.findall(r"\d+", b))
    digit_hit = sum(ch.isdigit() and ch in b for ch in a)
    num_bonus = (len(nums_a & nums_b) / max(1, len(nums_a))) if nums_a else float(digit_hit > 0)

    return base + w_block * block_bonus + w_contain * contain_bonus + w_tok * tok_jacc + w_num * num_bonus


def _require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise ImportError("pandas is required for BranchList mapping after PowerWorld reads the cases") from exc
    return pd


def mapping_branch(outages, branch_list):
    """Map outage rows to a PowerWorld BranchList dataframe.

    This is the same mapping idea as the reference code:
    first match by EMSName, then use From/To station, kV, equipment type, and a
    fuzzy EMSName score for rows not found by direct EMSName.
    """

    pd = _require_pandas()
    outages = pd.DataFrame([add_ems_name(row) for row in outages]).copy()
    if outages.empty:
        return outages

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
    unmapped_mask = outages["FromBusNum"].isna()
    if not unmapped_mask.any():
        return outages

    temp = outages.loc[unmapped_mask, ["From_Station", "To_Station", "KV", "EMSName", "Equipment_Type"]].copy()
    temp["rowid"] = temp.index
    temp["To_Station"] = temp["To_Station"].fillna(temp["From_Station"])
    temp["KV"] = temp["KV"].astype(float).round(1)

    branch_double = branch_list.rename(
        columns={
            "FromBusNum": "ToBusNum",
            "ToBusNum": "FromBusNum",
            "FromEMSName": "ToEMSName",
            "ToEMSName": "FromEMSName",
            "FromBusKV": "ToBusKV",
            "ToBusKV": "FromBusKV",
        }
    )
    branch_double = pd.concat([branch_list, branch_double], ignore_index=True)
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
    temp_mapped.sort_values(by=["rowid", "score"], ascending=[True, False], inplace=True)
    temp_mapped.drop_duplicates(subset=["rowid"], keep="first", inplace=True)
    temp_mapped = temp_mapped.set_index("rowid").reindex(temp["rowid"])
    temp_mapped.rename(columns={"EMSName_y": "EMSName"}, inplace=True)

    cols_fill = ["EMSName", "FromEMSName", "FromBusKV", "ToEMSName", "ToBusKV", "Circuit", "FromBusNum", "ToBusNum"]
    cols_fill = [col for col in cols_fill if col in temp_mapped.columns and col in outages.columns]
    if cols_fill:
        outages.loc[unmapped_mask, cols_fill] = temp_mapped[cols_fill].values

    return outages.loc[~outages["FromBusNum"].isna()].copy()


def map_outage_file_to_branch_lists(xml_file: str | Path, se_raw_file: str | Path, quarter_branch_list, se_branch_list):
    """Read one XML outage file and map active OOS outages to both BranchLists."""

    se_time = parse_se_datetime(se_raw_file)
    active = active_oos_outages(read_planned_outage_xml(xml_file), se_time)
    return {
        "quarter": mapping_branch(active, quarter_branch_list),
        "se": mapping_branch(active, se_branch_list),
        "future_retired": find_future_equipment_retired_lines(active, quarter_branch_list),
    }


def find_future_equipment_retired_lines(active_outages, quarter_branch_list):
    """Find original A-B lines that should stay open for Future Equipment outages.

    For a group with future lines A-C and C-B, the original A-B branch is looked
    up in the quarterly BranchList.  These returned rows are candidates to keep
    open when the future equipment is already in service in the SE case.
    """

    pd = _require_pandas()
    outages = pd.DataFrame([add_ems_name(row) for row in active_outages]).copy()
    if outages.empty or "Priority" not in outages:
        return outages.iloc[0:0].copy()

    future = outages[outages["Priority"].astype(str).str.strip().str.upper() == "FUTURE EQUIPMENT"].copy()
    if future.empty:
        return future

    future["group_key"] = future["Outage_Request_ID"].fillna("").astype(str).str.strip()
    missing_group = future["group_key"] == ""
    future.loc[missing_group, "group_key"] = future.loc[missing_group].apply(
        lambda row: "|".join(
            str(row.get(col, "")).strip()
            for col in ["Planned_Start", "Planned_End", "Priority", "KV"]
        ),
        axis=1,
    )

    retired_rows = []
    branch_double = _double_sided_branch_list(quarter_branch_list)
    for _, group in future.groupby("group_key"):
        stations = []
        for _, row in group.iterrows():
            stations.append(str(row.get("From_Station", "")).strip())
            stations.append(str(row.get("To_Station", "")).strip())
        station_counts = pd.Series([station for station in stations if station]).value_counts()
        if len(station_counts) < 3:
            continue

        center_station = station_counts.index[0]
        end_stations = [station for station in station_counts.index if station != center_station][:2]
        if len(end_stations) != 2:
            continue

        kv = float(group["KV"].dropna().iloc[0]) if not group["KV"].dropna().empty else None
        retired = branch_double[
            (branch_double["FromEMSName"].isin([end_stations[0], end_stations[1]]))
            & (branch_double["ToEMSName"].isin([end_stations[0], end_stations[1]]))
        ]
        if kv is not None and "KV" in retired:
            retired = retired[retired["KV"].astype(float).round(1) == round(kv, 1)]
        retired_rows.append(retired)

    if not retired_rows:
        return quarter_branch_list.iloc[0:0].copy()
    return pd.concat(retired_rows, ignore_index=True).drop_duplicates()


def _double_sided_branch_list(branch_list):
    pd = _require_pandas()
    reverse = branch_list.rename(
        columns={
            "FromBusNum": "ToBusNum",
            "ToBusNum": "FromBusNum",
            "FromEMSName": "ToEMSName",
            "ToEMSName": "FromEMSName",
            "FromBusKV": "ToBusKV",
            "ToBusKV": "FromBusKV",
        }
    )
    result = pd.concat([branch_list, reverse], ignore_index=True)
    result["KV"] = result[["FromBusKV", "ToBusKV"]].max(axis=1).astype(float).round(1)
    return result


def print_planned_outage_match(se_raw_file: str | Path, outage_file: str | Path) -> None:
    print(f"SE raw file: {format_path_for_output(se_raw_file)}")
    print(f"Planned outage XML: {format_path_for_output(outage_file)}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find the planned outage XML for one MISO SE raw file.")
    parser.add_argument("--se-file", required=True, help="SE raw filename/path, for example miso_se_20260427-0000_AREVA.raw")
    parser.add_argument("--planned-outage-root", default=DEFAULT_PLANNED_OUTAGE_ROOT, help="Folder containing planned outage XML files.")
    parser.add_argument("--hour-offset", type=int, default=4, help="Planned outage filename hour offset from SE hour. Examples use 4.")
    parser.add_argument(
        "--require-active-outage",
        action="store_true",
        help="Require the XML to contain at least one active OOS outage at the SE time.",
    )
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

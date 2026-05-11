"""Map MISO SE raw files to the appropriate quarterly EMS model.

The date is normally taken from a SE raw filename such as
``miso_se_20260427-1800_AREVA.raw``.  The YYYYMMDD portion determines both the
SE folder (``MISO_SE/YYYY``) and the quarterly EMS model folder/name.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Sequence


DEFAULT_QUARTER_MODEL_ROOT = r"G:\Power\MISO\Quarterly EMS Models"
DEFAULT_SE_ROOT = r"G:\Power\MISO\MISO_SE"
DEFAULT_PLANNED_OUTAGE_ROOT = r"G:\Power\MISO\Planned Outages"
SE_RAW_RE = re.compile(r"^miso_se_(?P<date>\d{8})-(?P<time>\d{4})_AREVA\.raw$", re.IGNORECASE)
PLANNED_OUTAGE_RE = re.compile(
    r"^2308_Planned_Outages_(?P<stamp>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})\.xml$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QuarterModel:
    """Quarterly EMS model selected for a study date."""

    study_date: date
    quarter_year: int
    quarter_month: int
    quarter_name: str
    folder: Path
    file_name: str
    path: Path


@dataclass(frozen=True)
class MisoRawMapping:
    """The four SE raw files for a date and their matching quarter model."""

    study_date: date
    quarter_model: QuarterModel
    se_raw_files: tuple[Path, ...]


@dataclass(frozen=True)
class PlannedOutageFile:
    """Planned outage XML file selected for a SE case."""

    path: Path
    timestamp: datetime


@dataclass(frozen=True)
class SeCaseMapping:
    """One SE raw file with its quarterly model and planned outage XML."""

    se_raw_file: Path
    se_time: datetime
    quarter_model: QuarterModel
    planned_outage_file: Path


def format_path_for_output(path: str | Path) -> str:
    """Display Windows-drive paths with backslashes even when run on Linux."""

    value = str(path)
    if re.match(r"^[A-Za-z]:\\", value):
        return value.replace("/", "\\")
    return value


def parse_se_datetime(value: str | Path) -> datetime:
    """Parse YYYYMMDD-HHMM from a MISO SE raw filename or path."""

    file_name = re.split(r"[\\/]", str(value).strip())[-1]
    se_match = SE_RAW_RE.match(file_name)
    if not se_match:
        raise ValueError(f"Could not parse SE date/time from {value!r}")
    return datetime.strptime(f"{se_match.group('date')}-{se_match.group('time')}", "%Y%m%d-%H%M")


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


def parse_study_date(value: str | date | None) -> date:
    """Parse a study date from YYYYMMDD, YYYY-MM-DD, or a SE raw filename."""

    if value is None:
        return date.today()
    if isinstance(value, date):
        return value

    stripped = str(value).strip()
    try:
        return parse_se_datetime(stripped).date()
    except ValueError:
        pass

    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(stripped, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Could not parse study date from {value!r}; expected YYYYMMDD, YYYY-MM-DD, or SE raw filename")


def quarter_for_date(study_date: date) -> tuple[int, int, str]:
    """Return the quarter model year, month, and month abbreviation for a date."""

    month = study_date.month
    if month in (1, 2):
        return study_date.year - 1, 12, "Dec"
    if month in (3, 4, 5):
        return study_date.year, 3, "Mar"
    if month in (6, 7, 8):
        return study_date.year, 6, "Jun"
    if month in (9, 10, 11):
        return study_date.year, 9, "Sep"
    return study_date.year, 12, "Dec"


def expected_quarter_model(study_date: date, quarter_model_root: str | Path = DEFAULT_QUARTER_MODEL_ROOT) -> QuarterModel:
    """Build the expected quarter model path for a study date."""

    quarter_year, quarter_month, quarter_name = quarter_for_date(study_date)
    folder = Path(quarter_model_root) / f"{quarter_year}{quarter_month:02d}"
    file_name = f"{quarter_name}{quarter_year}_final.raw"
    return QuarterModel(
        study_date=study_date,
        quarter_year=quarter_year,
        quarter_month=quarter_month,
        quarter_name=quarter_name,
        folder=folder,
        file_name=file_name,
        path=folder / file_name,
    )


def find_quarter_model(study_date: date, quarter_model_root: str | Path = DEFAULT_QUARTER_MODEL_ROOT) -> QuarterModel:
    """Find the quarter model file, requiring a final.raw file to exist."""

    model = expected_quarter_model(study_date, quarter_model_root)
    if model.path.is_file():
        return model

    candidates: list[Path] = []
    if model.folder.is_dir():
        prefix = f"{model.quarter_name}{model.quarter_year}".lower()
        candidates = sorted(
            path
            for path in model.folder.iterdir()
            if path.is_file() and path.name.lower().startswith(prefix) and path.name.lower().endswith("final.raw")
        )
    if len(candidates) == 1:
        candidate = candidates[0]
        return QuarterModel(
            study_date=model.study_date,
            quarter_year=model.quarter_year,
            quarter_month=model.quarter_month,
            quarter_name=model.quarter_name,
            folder=model.folder,
            file_name=candidate.name,
            path=candidate,
        )

    if candidates:
        raise FileNotFoundError(
            f"Expected one {model.quarter_name}{model.quarter_year}*final.raw file in {model.folder}, "
            f"found {len(candidates)}: {', '.join(path.name for path in candidates)}"
        )
    raise FileNotFoundError(f"Quarter model not found: {model.path}")


def se_year_folder(study_date: date, se_root: str | Path = DEFAULT_SE_ROOT) -> Path:
    """Return the SE folder for the study date year."""

    return Path(se_root) / f"{study_date.year}"


def _se_raw_sort_key(path: Path) -> tuple[str, str]:
    match = SE_RAW_RE.match(path.name)
    if not match:
        return ("9999", path.name)
    return (match.group("time"), path.name)


def find_se_raw_files(
    study_date: date,
    se_root: str | Path = DEFAULT_SE_ROOT,
    *,
    expected_count: int | None = 4,
) -> tuple[Path, ...]:
    """Find same-day MISO SE raw files under MISO_SE/YYYY.

    Files are matched by ``miso_se_YYYYMMDD-HHMM_AREVA.raw`` and returned in
    HHMM order.  By default this requires exactly four files for the date.
    """

    folder = se_year_folder(study_date, se_root)
    if not folder.is_dir():
        raise FileNotFoundError(f"SE folder not found: {folder}")

    yyyymmdd = study_date.strftime("%Y%m%d")
    files = tuple(
        sorted(
            (
                path
                for path in folder.iterdir()
                if path.is_file()
                and (match := SE_RAW_RE.match(path.name))
                and match.group("date") == yyyymmdd
            ),
            key=_se_raw_sort_key,
        )
    )

    if expected_count is not None and len(files) != expected_count:
        raise FileNotFoundError(f"Expected {expected_count} SE raw files for {yyyymmdd} in {folder}, found {len(files)}")
    return files


def find_planned_outage_file(
    se_raw_file: str | Path,
    planned_outage_root: str | Path = DEFAULT_PLANNED_OUTAGE_ROOT,
    *,
    hour_offset: int = 4,
) -> Path:
    """Find the latest planned outage XML with filename hour matching the SE case."""

    se_time = parse_se_datetime(se_raw_file)
    adjusted_se_time = se_time + timedelta(hours=hour_offset)
    target_hour = planned_outage_hour_for_se_time(se_time, hour_offset)

    matches: list[PlannedOutageFile] = []
    for path in Path(planned_outage_root).glob("**/2308_Planned_Outages_*.xml"):
        if not path.is_file():
            continue
        try:
            outage_time = parse_planned_outage_timestamp(path)
        except ValueError:
            continue
        if outage_time.hour == target_hour and outage_time <= adjusted_se_time:
            matches.append(PlannedOutageFile(path, outage_time))

    if not matches:
        raise FileNotFoundError(f"No planned outage XML found for {se_raw_file} with filename hour {target_hour:02d}")
    return max(matches, key=lambda item: item.timestamp).path


def build_mapping(
    study_date: str | date | None = None,
    *,
    quarter_model_root: str | Path = DEFAULT_QUARTER_MODEL_ROOT,
    se_root: str | Path = DEFAULT_SE_ROOT,
    expected_se_count: int | None = 4,
) -> MisoRawMapping:
    """Build the SE raw-to-quarter-model mapping for a study date."""

    parsed_date = parse_study_date(study_date)
    quarter_model = find_quarter_model(parsed_date, quarter_model_root)
    se_raw_files = find_se_raw_files(parsed_date, se_root, expected_count=expected_se_count)
    return MisoRawMapping(parsed_date, quarter_model, se_raw_files)


def find_inputs_for_se_raw(
    se_raw_file: str | Path,
    quarter_model_root: str | Path = DEFAULT_QUARTER_MODEL_ROOT,
    planned_outage_root: str | Path = DEFAULT_PLANNED_OUTAGE_ROOT,
    *,
    hour_offset: int = 4,
) -> SeCaseMapping:
    """Find quarter model and planned outage XML for one SE raw file."""

    se_time = parse_se_datetime(se_raw_file)
    return SeCaseMapping(
        se_raw_file=Path(se_raw_file),
        se_time=se_time,
        quarter_model=find_quarter_model(se_time.date(), quarter_model_root),
        planned_outage_file=find_planned_outage_file(se_raw_file, planned_outage_root, hour_offset=hour_offset),
    )


def build_case_mappings(
    study_date: str | date | None = None,
    *,
    quarter_model_root: str | Path = DEFAULT_QUARTER_MODEL_ROOT,
    se_root: str | Path = DEFAULT_SE_ROOT,
    planned_outage_root: str | Path = DEFAULT_PLANNED_OUTAGE_ROOT,
    expected_se_count: int | None = 4,
    hour_offset: int = 4,
) -> tuple[SeCaseMapping, ...]:
    """Find SE raw files, matching outage XMLs, and quarter model for a date."""

    parsed_date = parse_study_date(study_date)
    raw_mapping = build_mapping(
        parsed_date,
        quarter_model_root=quarter_model_root,
        se_root=se_root,
        expected_se_count=expected_se_count,
    )
    return tuple(
        SeCaseMapping(
            se_raw_file=se_file,
            se_time=parse_se_datetime(se_file),
            quarter_model=raw_mapping.quarter_model,
            planned_outage_file=find_planned_outage_file(se_file, planned_outage_root, hour_offset=hour_offset),
        )
        for se_file in raw_mapping.se_raw_files
    )


def print_case_mappings(case_mappings: tuple[SeCaseMapping, ...]) -> None:
    """Print SE, outage XML, and quarter model mappings."""

    for case in case_mappings:
        print(f"SE raw file: {format_path_for_output(case.se_raw_file)}")
        print(f"SE time: {case.se_time:%Y-%m-%d %H:%M}")
        print(f"Quarter model: {format_path_for_output(case.quarter_model.path)}")
        print(f"Planned outage XML: {format_path_for_output(case.planned_outage_file)}")
        print()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Map MISO SE raw files to planned outage XMLs and the quarter model.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--date", help="Study date as YYYYMMDD or YYYY-MM-DD. Defaults to today when omitted.")
    source.add_argument("--se-file", help="One SE raw filename/path.")
    parser.add_argument("--quarter-model-root", default=DEFAULT_QUARTER_MODEL_ROOT, help="Root folder for quarterly EMS models.")
    parser.add_argument("--se-root", default=DEFAULT_SE_ROOT, help="Root folder for MISO SE raw files.")
    parser.add_argument("--planned-outage-root", default=DEFAULT_PLANNED_OUTAGE_ROOT, help="Root folder for planned outage XML files.")
    parser.add_argument("--expected-se-count", type=int, default=4, help="Required number of same-day SE raw files.")
    parser.add_argument("--hour-offset", type=int, default=4, help="Planned outage filename hour offset from SE hour.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    date_input = args.se_file or args.date
    try:
        if args.se_file:
            case_mappings = (
                find_inputs_for_se_raw(
                    args.se_file,
                    quarter_model_root=args.quarter_model_root,
                    planned_outage_root=args.planned_outage_root,
                    hour_offset=args.hour_offset,
                ),
            )
        else:
            case_mappings = build_case_mappings(
                date_input,
                quarter_model_root=args.quarter_model_root,
                se_root=args.se_root,
                planned_outage_root=args.planned_outage_root,
                expected_se_count=args.expected_se_count,
                hour_offset=args.hour_offset,
            )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    print_case_mappings(case_mappings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

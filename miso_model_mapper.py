"""Map MISO SE raw files to the appropriate quarterly EMS model.

The date is normally taken from a SE raw filename such as
``miso_se_20260427-1800_AREVA.raw``.  The YYYYMMDD portion determines both the
SE folder (``MISO_SE/YYYY``) and the quarterly EMS model folder/name.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_QUARTER_MODEL_ROOT = r"G:\Power\MISO\Quarterly EMS Models"
DEFAULT_SE_ROOT = r"G:\Power\MISO\MISO_SE"
SE_RAW_RE = re.compile(r"^miso_se_(?P<date>\d{8})-(?P<time>\d{4})_AREVA\.raw$", re.IGNORECASE)


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

    def to_json_dict(self) -> dict[str, object]:
        return {
            "date": self.study_date.isoformat(),
            "quarter_model": {
                "quarter": f"{self.quarter_model.quarter_name}{self.quarter_model.quarter_year}",
                "folder": format_path_for_output(self.quarter_model.folder),
                "file": self.quarter_model.file_name,
                "path": format_path_for_output(self.quarter_model.path),
            },
            "se_raw_files": [format_path_for_output(path) for path in self.se_raw_files],
        }


def format_path_for_output(path: str | Path) -> str:
    """Display Windows-drive paths with backslashes even when run on Linux."""

    value = str(path)
    if re.match(r"^[A-Za-z]:\\", value):
        return value.replace("/", "\\")
    return value


def parse_study_date(value: str | date | None) -> date:
    """Parse a study date from YYYYMMDD, YYYY-MM-DD, or a SE raw filename."""

    if value is None:
        return date.today()
    if isinstance(value, date):
        return value

    stripped = str(value).strip()
    file_name = re.split(r"[\\/]", stripped)[-1]
    se_match = SE_RAW_RE.match(file_name)
    if se_match:
        stripped = se_match.group("date")

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


def build_mapping(
    study_date: str | date | None = None,
    *,
    quarter_model_root: str | Path = DEFAULT_QUARTER_MODEL_ROOT,
    se_root: str | Path = DEFAULT_SE_ROOT,
    require_existing_model: bool = True,
    expected_se_count: int | None = 4,
) -> MisoRawMapping:
    """Build the SE raw-to-quarter-model mapping for a study date."""

    parsed_date = parse_study_date(study_date)
    quarter_model = (
        find_quarter_model(parsed_date, quarter_model_root)
        if require_existing_model
        else expected_quarter_model(parsed_date, quarter_model_root)
    )
    se_raw_files = find_se_raw_files(parsed_date, se_root, expected_count=expected_se_count)
    return MisoRawMapping(parsed_date, quarter_model, se_raw_files)


def build_expected_mapping(
    study_date: str | date | None = None,
    *,
    quarter_model_root: str | Path = DEFAULT_QUARTER_MODEL_ROOT,
    se_root: str | Path = DEFAULT_SE_ROOT,
) -> MisoRawMapping:
    """Build expected paths without requiring files to exist."""

    parsed_date = parse_study_date(study_date)
    quarter_model = expected_quarter_model(parsed_date, quarter_model_root)
    folder = se_year_folder(parsed_date, se_root)
    yyyymmdd = parsed_date.strftime("%Y%m%d")
    expected_se_files = tuple(folder / f"miso_se_{yyyymmdd}-{hour:02d}00_AREVA.raw" for hour in (0, 6, 12, 18))
    return MisoRawMapping(parsed_date, quarter_model, expected_se_files)


def _json_default(value: object) -> str:
    if isinstance(value, (Path, date)):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Map a MISO SE raw date to its quarterly EMS model.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--date", help="Study date as YYYYMMDD or YYYY-MM-DD. Defaults to today when omitted.")
    source.add_argument("--se-file", help="SE raw filename/path; YYYYMMDD is extracted from the filename.")
    parser.add_argument("--quarter-model-root", default=DEFAULT_QUARTER_MODEL_ROOT, help="Root folder for quarterly EMS models.")
    parser.add_argument("--se-root", default=DEFAULT_SE_ROOT, help="Root folder for MISO SE raw files.")
    parser.add_argument("--expected-se-count", type=int, default=4, help="Required number of same-day SE raw files.")
    parser.add_argument(
        "--expected-only",
        action="store_true",
        help="Print the expected model and four standard 0000/0600/1200/1800 SE paths without checking the filesystem.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    date_input = args.se_file or args.date
    try:
        if args.expected_only:
            mapping = build_expected_mapping(date_input, quarter_model_root=args.quarter_model_root, se_root=args.se_root)
        else:
            mapping = build_mapping(
                date_input,
                quarter_model_root=args.quarter_model_root,
                se_root=args.se_root,
                expected_se_count=args.expected_se_count,
            )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    print(json.dumps(mapping.to_json_dict(), indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

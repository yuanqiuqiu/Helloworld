import argparse
from pathlib import Path

import pandas as pd


ROOTPATH = r"G:\Power\MISO\FTR Results"
AUCTION_YEAR = "2025-26"
AUCTION_TYPE = "Monthly"
AUCTION_NAME = "May26"
AUCTION_FOLDER = "2026_05"
AUCTION_DATE = "05/01/2026"
PORTFOLIO_MONTH = "05/01/2026"

RESULTS_SUBFOLDER = "Private"
AWARDED_PATH_FOLDER = r"C:\Users\joanna.wu\python_projects\MISO_auctions\awarded_path"
MASTER_FILE_NAME = "awarded_paths_master.xlsx"
OUTPUT_FILE_SUFFIX = "_yesenergy_portfolio.xlsx"
ALL_OUTPUT_FILE_SUFFIX = "_all_yesenergy_portfolio.xlsx"

# Columns to extract from each result file.
RESULT_COLS = [
    "Portfolio",
    "Source",
    "Sink",
    "StartDate",
    "EndDate",
    "HedgeType",
    "Type",
    "Class",
    "Round",
    "AwardedMW",
    "ClearingPrice",
]

# YesEnergy output column order.
YE_COLS = [
    "ISO",
    "portfolioname",
    "bookname",
    "sourcename",
    "sinkname",
    "peaktype",
    "hedgetype",
    "tradetype",
    "contractstartdate",
    "auctiondate",
    "contracttype",
    "round",
    "pathsize",
    "costoverride ($/MW)",
]

# Extra master-file columns keep imports traceable and make repeated runs safer.
MASTER_METADATA_COLS = ["auctionyear", "auctiontype", "auctionname", "sourcefile"]
MASTER_COLS = YE_COLS + MASTER_METADATA_COLS

AGGREGATION_KEYS = ["sourcename", "sinkname", "peaktype", "contractstartdate"]


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Append new MISO FTR auction awards to a master file, expand quarters "
            "to monthly paths, aggregate active paths, and write a YesEnergy portfolio."
        )
    )
    parser.add_argument("--rootpath", default=ROOTPATH)
    parser.add_argument("--auction-year", default=AUCTION_YEAR)
    parser.add_argument("--auction-type", default=AUCTION_TYPE)
    parser.add_argument("--auction-name", default=AUCTION_NAME)
    parser.add_argument("--auction-folder", default=AUCTION_FOLDER)
    parser.add_argument("--auction-date", default=AUCTION_DATE)
    parser.add_argument(
        "--portfolio-month",
        default=PORTFOLIO_MONTH,
        help=(
            "Month to include in the regular YesEnergy output. Use the first "
            "day of the target month, e.g. 06/01/2026 for an annual-auction "
            "quarter that shares auction date 04/01/2026."
        ),
    )
    parser.add_argument("--awarded-path-folder", default=AWARDED_PATH_FOLDER)
    parser.add_argument("--results-folder")
    parser.add_argument("--master-file")
    parser.add_argument("--output-file")
    parser.add_argument("--all-output-file")
    return parser.parse_args()


def first_day_of_month(value):
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return pd.NaT
    return dt.to_period("M").to_timestamp()


def portfolio_month_file_prefix(portfolio_month_start):
    return portfolio_month_start.strftime("%Y_%m")


def determine_contract_type(start_date, end_date):
    """Return 'Q' if the source award spans roughly a quarter, otherwise 'M'."""
    if pd.isna(start_date) or pd.isna(end_date):
        return "M"
    return "Q" if (end_date - start_date).days >= 60 else "M"


def monthly_contract_starts(start_date, end_date):
    """Expand the source award to one first-of-month contract date per month."""
    contract_type = determine_contract_type(start_date, end_date)
    start_month = first_day_of_month(start_date)

    if pd.isna(start_month):
        return []

    if contract_type != "Q":
        return [start_month]

    end_month = first_day_of_month(end_date)
    if pd.isna(end_month) or end_month < start_month:
        return [start_month]

    return list(pd.date_range(start=start_month, end=end_month, freq="MS"))


def build_monthly_yesenergy_rows(row, auction_date, metadata):
    """Map one result-file row to one or more monthly YesEnergy-shaped rows."""
    rows = []
    for contract_start in monthly_contract_starts(row["StartDate"], row["EndDate"]):
        rows.append(
            {
                "ISO": "MISO",
                "portfolioname": row["Portfolio"],
                "bookname": "joanna",
                "sourcename": row["Source"],
                "sinkname": row["Sink"],
                "peaktype": row["Class"],
                "hedgetype": "Obligation",
                "tradetype": row["Type"],
                "contractstartdate": contract_start,
                "auctiondate": auction_date,
                "contracttype": "M",
                "round": row["Round"],
                "pathsize": row["AwardedMW"],
                "costoverride ($/MW)": row["ClearingPrice"],
                **metadata,
            }
        )
    return rows


def process_result_file(filepath, auction_date, metadata):
    """
    Read one AUCTION_PRIVATE_RESULTS CSV, expand all awards to monthly rows,
    and return a YesEnergy-shaped DataFrame for the master file.
    """
    df = pd.read_csv(filepath)

    missing = [c for c in RESULT_COLS if c not in df.columns]
    if missing:
        print(f"  [WARN] Missing columns {missing} in {filepath.name}")
        return None

    df = df[RESULT_COLS].copy()
    df["StartDate"] = pd.to_datetime(df["StartDate"], errors="coerce")
    df["EndDate"] = pd.to_datetime(df["EndDate"], errors="coerce")
    df["AwardedMW"] = pd.to_numeric(df["AwardedMW"], errors="coerce")
    df["ClearingPrice"] = pd.to_numeric(df["ClearingPrice"], errors="coerce")

    df.dropna(inplace=True)
    df = df[df["AwardedMW"] != 0]

    if df.empty:
        print(f"  [WARN] No valid non-zero rows after cleanup: {filepath.name}")
        return None

    rows = []
    for _, row in df.iterrows():
        rows.extend(build_monthly_yesenergy_rows(row, auction_date, metadata))

    return pd.DataFrame(rows, columns=MASTER_COLS)


def find_result_files(results_folder):
    return sorted(
        f
        for f in results_folder.iterdir()
        if f.is_file()
        and f.name.upper().startswith("AUCTION_PRIVATE_RESULTS")
        and f.suffix.lower() == ".csv"
    )


def read_table(path):
    if path.suffix.lower() in [".xlsx", ".xlsm", ".xls"]:
        return pd.read_excel(path)
    return pd.read_csv(path)


def write_table(df, path, sheet_name):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in [".xlsx", ".xlsm", ".xls"]:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
    else:
        df.to_csv(path, index=False)


def load_master(master_file):
    if not master_file.exists():
        return pd.DataFrame(columns=MASTER_COLS)

    master = read_table(master_file)
    missing = [c for c in YE_COLS if c not in master.columns]
    if missing:
        raise ValueError(f"Master file is missing required columns: {missing}")

    for col in MASTER_METADATA_COLS:
        if col not in master.columns:
            master[col] = ""

    return normalize_portfolio_frame(master[MASTER_COLS].copy())


def normalize_portfolio_frame(df):
    if df.empty:
        return pd.DataFrame(columns=MASTER_COLS)

    df = df.copy()
    df["contractstartdate"] = df["contractstartdate"].map(first_day_of_month)
    df["auctiondate"] = pd.to_datetime(df["auctiondate"], errors="coerce")
    df["pathsize"] = pd.to_numeric(df["pathsize"], errors="coerce")
    df["costoverride ($/MW)"] = pd.to_numeric(df["costoverride ($/MW)"], errors="coerce")

    required = AGGREGATION_KEYS + ["pathsize", "costoverride ($/MW)"]
    df.dropna(subset=required, inplace=True)
    df = df[df["pathsize"] != 0]
    df["contracttype"] = "M"

    return df[MASTER_COLS]


def format_output_dates(df):
    df = df.copy()
    df["contractstartdate"] = pd.to_datetime(df["contractstartdate"]).dt.strftime("%m/%d/%Y")
    df["auctiondate"] = pd.to_datetime(df["auctiondate"]).dt.strftime("%m/%d/%Y")
    return df


def pick_output_value(values, fallback=""):
    unique_values = [v for v in pd.unique(values.dropna()) if str(v).strip() != ""]
    if not unique_values:
        return fallback
    if len(unique_values) == 1:
        return unique_values[0]
    return "Combined"


def weighted_price(group):
    mw_sum = group["pathsize"].sum()
    if mw_sum == 0:
        return pd.NA
    return (group["pathsize"] * group["costoverride ($/MW)"]).sum() / mw_sum


def aggregate_yesenergy_portfolio(active_master, auction_date):
    if active_master.empty:
        return pd.DataFrame(columns=YE_COLS)

    rows = []
    for keys, group in active_master.groupby(AGGREGATION_KEYS, dropna=False, sort=True):
        sourcename, sinkname, peaktype, contractstartdate = keys
        pathsize = group["pathsize"].sum()
        price = weighted_price(group)
        if pathsize == 0 or pd.isna(price):
            continue

        rows.append(
            {
                "ISO": pick_output_value(group["ISO"], "MISO"),
                "portfolioname": pick_output_value(group["portfolioname"]),
                "bookname": pick_output_value(group["bookname"], "joanna"),
                "sourcename": sourcename,
                "sinkname": sinkname,
                "peaktype": peaktype,
                "hedgetype": pick_output_value(group["hedgetype"], "Obligation"),
                "tradetype": pick_output_value(group["tradetype"]),
                "contractstartdate": contractstartdate,
                "auctiondate": auction_date,
                "contracttype": "M",
                "round": pick_output_value(group["round"]),
                "pathsize": pathsize,
                "costoverride ($/MW)": price,
            }
        )

    result = pd.DataFrame(rows, columns=YE_COLS)
    if result.empty:
        return result

    return result.sort_values(
        ["contractstartdate", "peaktype", "sourcename", "sinkname"], kind="stable"
    )


def main():
    args = parse_args()

    rootpath = Path(args.rootpath)
    results_folder = (
        Path(args.results_folder)
        if args.results_folder
        else rootpath / args.auction_folder / RESULTS_SUBFOLDER
    )
    awarded_path_folder = Path(args.awarded_path_folder)
    master_file = (
        Path(args.master_file)
        if args.master_file
        else awarded_path_folder / MASTER_FILE_NAME
    )
    all_output_file = (
        Path(args.all_output_file)
        if args.all_output_file
        else awarded_path_folder / f"{args.auction_name}{ALL_OUTPUT_FILE_SUFFIX}"
    )
    auction_date = pd.to_datetime(args.auction_date, errors="raise")
    portfolio_month_start = first_day_of_month(args.portfolio_month)
    if pd.isna(portfolio_month_start):
        raise ValueError(
            f"Unable to parse --portfolio-month as a date: {args.portfolio_month}"
        )
    output_file = (
        Path(args.output_file)
        if args.output_file
        else awarded_path_folder
        / (
            f"{portfolio_month_file_prefix(portfolio_month_start)}_"
            f"{args.auction_name}{OUTPUT_FILE_SUFFIX}"
        )
    )

    result_files = find_result_files(results_folder)
    if not result_files:
        print(f"No AUCTION_PRIVATE_RESULTS CSV files found in:\n  {results_folder}")
        return

    print(f"Found {len(result_files)} CSV file(s) in {results_folder}")
    print(f"Using master file: {master_file}")

    master = load_master(master_file)
    new_frames = []

    for filepath in result_files:
        print(f"Processing: {filepath.name}")
        metadata = {
            "auctionyear": args.auction_year,
            "auctiontype": args.auction_type,
            "auctionname": args.auction_name,
            "sourcefile": filepath.name,
        }
        result_df = process_result_file(filepath, auction_date, metadata)
        if result_df is not None:
            new_frames.append(result_df)
            print(f"  Added monthly award rows: {len(result_df)}")

    if new_frames:
        master = pd.concat([master, *new_frames], ignore_index=True)

    master = normalize_portfolio_frame(master)
    before_dedupe = len(master)
    master.drop_duplicates(subset=MASTER_COLS, keep="last", inplace=True)
    if len(master) != before_dedupe:
        print(f"Removed {before_dedupe - len(master)} duplicate master row(s)")

    before_expiry = len(master)
    active_master = master[
        master["contractstartdate"] >= portfolio_month_start
    ].copy()
    expired_count = before_expiry - len(active_master)
    if expired_count:
        print(f"Deleted {expired_count} expired master row(s)")

    portfolio_month_master = active_master[
        active_master["contractstartdate"] == portfolio_month_start
    ].copy()
    portfolio = aggregate_yesenergy_portfolio(portfolio_month_master, auction_date)
    all_portfolio = aggregate_yesenergy_portfolio(active_master, auction_date)

    write_table(format_output_dates(portfolio), output_file, "Portfolio")
    write_table(format_output_dates(all_portfolio), all_output_file, "Portfolio")
    write_table(format_output_dates(active_master), master_file, "Master")

    print(
        f"Saved {portfolio_month_start.strftime('%m/%d/%Y')} YesEnergy portfolio: "
        f"{output_file} "
        f"({len(portfolio)} row(s))"
    )
    print(
        f"Saved all-active YesEnergy portfolio: {all_output_file} "
        f"({len(all_portfolio)} row(s))"
    )
    print(f"Saved active master file: {master_file} ({len(active_master)} row(s))")
    print("Done.")


if __name__ == "__main__":
    main()

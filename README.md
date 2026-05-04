# Auction Results to YesEnergy Portfolio

Use `auction_to_yesenergy_portfolio.py` to append new MISO FTR auction award
results to an active master file, expand quarterly awards into monthly paths,
combine matching paths, and write a YesEnergy portfolio workbook.

Default run:

```bash
python3 -m pip install -r requirements.txt
python3 auction_to_yesenergy_portfolio.py
```

Useful overrides:

```bash
python3 auction_to_yesenergy_portfolio.py \
  --rootpath "G:\Power\MISO\FTR Results" \
  --awarded-path-folder "C:\Users\joanna.wu\python_projects\MISO_auctions\awarded_path" \
  --auction-folder "2026_05" \
  --auction-name "May26" \
  --auction-date "05/01/2026" \
  --portfolio-month "05/01/2026"
```

The script reads `AUCTION_PRIVATE_RESULTS*.csv` files from the auction
`Private` folder, updates `awarded_paths_master.xlsx` in the awarded-path
folder, removes paths with `contractstartdate` before the portfolio month, and
writes two YesEnergy outputs to the same awarded-path folder:

- `*_yesenergy_portfolio.xlsx` includes only rows for `--portfolio-month`.
- `*_all_yesenergy_portfolio.xlsx` includes all active monthly rows from the
  master file.

For annual auctions, set `--auction-date` to the shared auction date, such as
`04/01/2026`, and set `--portfolio-month` to the quarterly month you want to
export, such as `06/01/2026`, `09/01/2026`, `12/01/2026`, or `03/01/2027`.
